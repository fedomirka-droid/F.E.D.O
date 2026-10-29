"""Sync Engine: очередь изменений, идемпотентность, конфликты.

Схема (без копирования файла SQLite):
  Desktop пишет локально + outbox → push(op_id, base_version) → HUB
  HUB применяет, пишет change_log → Desktop pull(cursor) → применяет у себя.

Конфликт = несовпадение base_version с серверной версией. Обе версии
сохраняются в SyncConflict; владелец решает, что применить.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import iso, utcnow
from ..models import (
    CalendarEvent,
    ChangeLog,
    OutboxEntry,
    ScheduleEntry,
    StudentProfile,
    SyncConflict,
    SyncOperation,
    SyncState,
    Task,
    UserPreference,
)

ENTITY_MODELS: dict[str, Any] = {
    "task": Task,
    "event": CalendarEvent,
    "schedule": ScheduleEntry,
    "preference": UserPreference,
    "student_profile": StudentProfile,
}

SYNC_FIELDS: dict[str, tuple[str, ...]] = {
    "task": ("title", "description", "priority", "status", "due_at", "remind_at",
             "planned_minutes", "actual_minutes", "category", "started_at", "completed_at"),
    "event": ("title", "description", "starts_at", "ends_at", "location", "category", "remind_at"),
    "schedule": ("group_name", "date", "slot", "start_time", "end_time", "subject",
                 "teacher", "room", "lesson_type", "source_file", "source_sheet"),
    "preference": ("key", "value"),
    "student_profile": ("group_name", "college", "specialty", "course", "semester",
                        "study_form", "student_card", "notes", "source"),
}

# Сущности с уникальностью на уровне владельца. Их id на разных устройствах
# может отличаться (например профиль студента выводится из owner_id, а он у
# каждого узла свой), поэтому перед созданием ищем запись по натуральному ключу
# и обновляем её — иначе UNIQUE-констрейнт ломает синхронизацию.
UNIQUE_ENTITY_KEYS: dict[str, tuple[str, ...]] = {
    "preference": ("key",),
    "student_profile": (),   # одна запись на владельца
}


def resolve_unique_entity(db: Session, owner_id: str, entity: str,
                          payload: dict) -> Any | None:
    """Найти существующую запись по натуральному ключу (или None)."""
    keys = UNIQUE_ENTITY_KEYS.get(entity)
    if keys is None:
        return None
    model = ENTITY_MODELS[entity]
    query = select(model).where(model.owner_id == owner_id)
    for key in keys:
        if key not in payload:
            return None
        query = query.where(getattr(model, key) == payload[key])
    return db.execute(query).scalars().first()


DATETIME_FIELDS = {
    "due_at", "remind_at", "started_at", "completed_at", "starts_at", "ends_at",
}


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        from datetime import timezone

        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def normalize_value(field: str, value: Any) -> Any:
    if field in DATETIME_FIELDS:
        return parse_dt(value)
    if field in ("planned_minutes", "actual_minutes", "slot"):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
    return value


def entity_to_dict(obj: Any) -> dict:
    """Сериализация синхронизируемой сущности."""
    entity = next((k for k, v in ENTITY_MODELS.items() if isinstance(obj, v)), None)
    data = {
        "id": obj.id,
        "version": obj.version,
        "updated_at": iso(obj.updated_at),
        "created_at": iso(obj.created_at),
        "deleted_at": iso(obj.deleted_at),
        "origin_device": obj.origin_device,
    }
    for field in SYNC_FIELDS[entity]:
        value = getattr(obj, field)
        data[field] = iso(value) if isinstance(value, datetime) else value
    return data


def _fields_equal(obj: Any, entity: str, payload: dict) -> bool:
    for field in SYNC_FIELDS[entity]:
        if field not in payload:
            continue
        current = getattr(obj, field)
        incoming = normalize_value(field, payload[field])
        if isinstance(current, datetime):
            if parse_dt(current) != (incoming if isinstance(incoming, datetime) else parse_dt(incoming)):
                return False
        elif current != incoming:
            return False
    return True


def _apply_payload(obj: Any, entity: str, payload: dict) -> None:
    for field in SYNC_FIELDS[entity]:
        if field in payload:
            setattr(obj, field, normalize_value(field, payload[field]))


def _record_change(db: Session, owner_id: str, entity: str, entity_id: str, obj: Any,
                   operation: str, device_id: str | None) -> ChangeLog:
    payload = entity_to_dict(obj)
    entry = ChangeLog(
        owner_id=owner_id,
        entity=entity,
        entity_id=entity_id,
        version=obj.version,
        operation=operation,
        payload=payload,
        device_id=device_id,
    )
    db.add(entry)
    db.flush()
    return entry


# --------------------------------------------------------------------------- #
# HUB: применение операции
# --------------------------------------------------------------------------- #
def apply_operation(db: Session, owner_id: str, device_id: str, entity: str,
                    entity_id: str, operation: str, payload: dict,
                    base_version: int, op_id: str) -> dict:
    """Применить одну операцию идемпотентно. Возвращает результат для клиента."""
    if entity not in ENTITY_MODELS:
        return {"status": "rejected", "reason": f"unknown entity: {entity}"}

    existing_op = db.execute(
        select(SyncOperation).where(SyncOperation.owner_id == owner_id, SyncOperation.op_id == op_id)
    ).scalar_one_or_none()
    if existing_op is not None:
        return {**existing_op.result, "idempotent": True}

    model = ENTITY_MODELS[entity]
    obj = db.get(model, entity_id)
    if obj is not None and obj.owner_id != owner_id:
        return {"status": "rejected", "reason": "entity belongs to another owner"}

    result: dict
    now = utcnow()

    if obj is None:
        if operation == "delete":
            result = {"status": "applied", "op_id": op_id, "entity_id": entity_id,
                      "version": 0, "noop": True}
        else:
            natural = resolve_unique_entity(db, owner_id, entity, payload)
            if natural is not None:
                # та же запись, что уже есть под другим id — обновляем её
                obj = natural
                entity_id = obj.id
                server_version = obj.version
                if _fields_equal(obj, entity, payload):
                    result = {"status": "applied", "op_id": op_id, "entity_id": entity_id,
                              "version": server_version, "updated_at": iso(obj.updated_at),
                              "duplicate": True, "resolved": "natural_key"}
                else:
                    _apply_payload(obj, entity, payload)
                    obj.version = server_version + 1
                    obj.updated_at = now
                    obj.origin_device = device_id
                    db.flush()
                    _record_change(db, owner_id, entity, entity_id, obj, "upsert", device_id)
                    result = {"status": "applied", "op_id": op_id, "entity_id": entity_id,
                              "version": obj.version, "resolved": "natural_key"}
                db.add(SyncOperation(owner_id=owner_id, op_id=op_id, device_id=device_id,
                                     entity=entity, entity_id=entity_id, result=result))
                db.flush()
                return result
            obj = model(id=entity_id, owner_id=owner_id, version=1,
                        origin_device=device_id, updated_at=now, created_at=now)
            # обязательные поля (title / date / key) — из payload
            _apply_payload(obj, entity, payload)
            db.add(obj)
            db.flush()
            _record_change(db, owner_id, entity, entity_id, obj, "upsert", device_id)
            result = {"status": "applied", "op_id": op_id, "entity_id": entity_id,
                      "version": obj.version, "updated_at": iso(obj.updated_at),
                      "resolved": "created"}
    else:
        server_version = obj.version
        if _fields_equal(obj, entity, payload) and (obj.deleted_at is not None) == (operation == "delete"):
            # повторная/дублирующая операция — ничего не меняем
            result = {"status": "applied", "op_id": op_id, "entity_id": entity_id,
                      "version": server_version, "updated_at": iso(obj.updated_at),
                      "duplicate": True}
        elif base_version == server_version:
            if operation == "delete":
                obj.deleted_at = now
            else:
                obj.deleted_at = None
                _apply_payload(obj, entity, payload)
            obj.version = server_version + 1
            obj.updated_at = now
            obj.origin_device = device_id
            db.flush()
            _record_change(db, owner_id, entity, entity_id, obj, operation, device_id)
            result = {"status": "applied", "op_id": op_id, "entity_id": entity_id,
                      "version": obj.version, "updated_at": iso(obj.updated_at)}
        else:
            conflict = SyncConflict(
                id=str(uuid.uuid4()), owner_id=owner_id, entity=entity, entity_id=entity_id,
                base_version=base_version, server_version=server_version,
                incoming={**payload, "operation": operation},
                server=entity_to_dict(obj), device_id=device_id,
            )
            db.add(conflict)
            db.flush()
            result = {
                "status": "conflict", "op_id": op_id, "entity_id": entity_id,
                "conflict_id": conflict.id, "server_version": server_version,
                "server": conflict.server, "base_version": base_version,
            }

    db.add(SyncOperation(owner_id=owner_id, op_id=op_id, device_id=device_id,
                         entity=entity, entity_id=entity_id, result=result))
    db.flush()
    return result


def push_operations(db: Session, owner_id: str, device_id: str, operations: list[dict]) -> list[dict]:
    results = []
    for op in operations:
        try:
            results.append(apply_operation(
                db, owner_id, device_id,
                entity=str(op.get("entity", "")),
                entity_id=str(op.get("entity_id", "")),
                operation=str(op.get("operation", "upsert")),
                payload=op.get("payload") or {},
                base_version=int(op.get("base_version") or 0),
                op_id=str(op.get("op_id") or uuid.uuid4()),
            ))
        except Exception as exc:  # одна плохая операция не ломает весь пакет
            db.rollback()
            results.append({"status": "error", "op_id": op.get("op_id"), "reason": str(exc)})
    return results


def pull_changes(db: Session, owner_id: str, cursor: int = 0, exclude_device: str | None = None,
                 limit: int = 500) -> dict:
    query = select(ChangeLog).where(ChangeLog.owner_id == owner_id, ChangeLog.id > cursor)
    if exclude_device:
        query = query.where(
            (ChangeLog.device_id.is_(None)) | (ChangeLog.device_id != exclude_device)
        )
    rows = db.execute(query.order_by(ChangeLog.id).limit(limit)).scalars().all()
    changes = [
        {"cursor": row.id, "entity": row.entity, "entity_id": row.entity_id,
         "version": row.version, "operation": row.operation, "payload": row.payload,
         "device_id": row.device_id, "created_at": iso(row.created_at)}
        for row in rows
    ]
    return {"changes": changes, "cursor": rows[-1].id if rows else cursor, "count": len(changes)}


# --------------------------------------------------------------------------- #
# Desktop: локальная очередь
# --------------------------------------------------------------------------- #
def enqueue_change(db: Session, owner_id: str, entity: str, entity_id: str,
                   operation: str, payload: dict, base_version: int) -> OutboxEntry:
    entry = OutboxEntry(
        op_id=str(uuid.uuid4()), owner_id=owner_id, entity=entity, entity_id=entity_id,
        operation=operation, payload=payload, base_version=base_version,
    )
    db.add(entry)
    db.flush()
    return entry


def pending_operations(db: Session, owner_id: str, limit: int = 100) -> list[OutboxEntry]:
    now = utcnow()
    rows = db.execute(
        select(OutboxEntry).where(
            OutboxEntry.owner_id == owner_id, OutboxEntry.next_attempt_at <= now
        ).order_by(OutboxEntry.id).limit(limit)
    ).scalars().all()
    return list(rows)


def backoff_seconds(attempts: int) -> int:
    """Экспоненциальный backoff с потолком."""
    return min(5 * (2 ** max(attempts - 1, 0)), 300)


def mark_failed(db: Session, entry: OutboxEntry, error: str) -> None:
    entry.attempts += 1
    entry.last_error = error[:255]
    entry.next_attempt_at = utcnow() + timedelta(seconds=backoff_seconds(entry.attempts))


def apply_remote_change(db: Session, owner_id: str, change: dict) -> str:
    """Применить изменение HUB локально. Возвращает 'applied'|'conflict'|'skipped'."""
    entity = change.get("entity")
    if entity not in ENTITY_MODELS:
        return "skipped"
    model = ENTITY_MODELS[entity]
    entity_id = change.get("entity_id")
    payload = change.get("payload") or {}
    remote_version = int(change.get("version") or 0)

    has_pending = db.execute(
        select(OutboxEntry).where(
            OutboxEntry.owner_id == owner_id,
            OutboxEntry.entity == entity,
            OutboxEntry.entity_id == entity_id,
        )
    ).first() is not None

    obj = db.get(model, entity_id)
    if obj is not None and obj.owner_id != owner_id:
        return "skipped"

    if has_pending:
        # локальная правка ещё в очереди → не затираем, фиксируем конфликт
        if obj is None or remote_version > obj.version:
            conflict = SyncConflict(
                id=str(uuid.uuid4()), owner_id=owner_id, entity=entity, entity_id=entity_id,
                base_version=obj.version if obj else 0, server_version=remote_version,
                incoming={"source": "local", "payload": entity_to_dict(obj) if obj else {}},
                server=payload, device_id=change.get("device_id") or "",
            )
            db.add(conflict)
            db.flush()
            return "conflict"
        return "skipped"

    if obj is None:
        if change.get("operation") == "delete":
            return "skipped"
        natural = resolve_unique_entity(db, owner_id, entity, payload)
        if natural is not None:
            # локальная копия той же логической записи под другим id
            obj = natural
        else:
            obj = model(id=entity_id, owner_id=owner_id, version=remote_version,
                        origin_device=change.get("device_id"))
            _apply_payload(obj, entity, payload)
            obj.updated_at = parse_dt(payload.get("updated_at")) or utcnow()
            obj.deleted_at = parse_dt(payload.get("deleted_at"))
            db.add(obj)
            db.flush()
            return "applied"
        _apply_payload(obj, entity, payload)
        obj.version = max(remote_version, int(obj.version or 0) + 1)
        obj.updated_at = parse_dt(payload.get("updated_at")) or utcnow()
        obj.deleted_at = parse_dt(payload.get("deleted_at"))
        db.flush()
        return "applied"

    if remote_version <= obj.version and (obj.deleted_at is not None) == bool(payload.get("deleted_at")):
        return "skipped"

    if remote_version == obj.version and obj.updated_at != parse_dt(payload.get("updated_at")):
        conflict = SyncConflict(
            id=str(uuid.uuid4()), owner_id=owner_id, entity=entity, entity_id=entity_id,
            base_version=obj.version, server_version=remote_version,
            incoming={"source": "local", "payload": entity_to_dict(obj)},
            server=payload, device_id=change.get("device_id") or "",
        )
        db.add(conflict)
        db.flush()
        return "conflict"

    _apply_payload(obj, entity, payload)
    obj.version = remote_version
    obj.updated_at = parse_dt(payload.get("updated_at")) or utcnow()
    obj.deleted_at = parse_dt(payload.get("deleted_at"))
    db.flush()
    return "applied"


def get_sync_state(db: Session, owner_id: str) -> SyncState:
    state = db.execute(select(SyncState)).scalars().first()
    if state is None:
        state = SyncState(id=1, owner_id=owner_id, cursor=0, online=False)
        db.add(state)
        db.flush()
    return state


def sync_status(db: Session, owner_id: str) -> dict:
    state = get_sync_state(db, owner_id)
    pending = db.execute(
        select(OutboxEntry).where(OutboxEntry.owner_id == owner_id)
    ).scalars().all()
    conflicts = db.execute(
        select(SyncConflict).where(SyncConflict.owner_id == owner_id, SyncConflict.status == "open")
    ).scalars().all()
    return {
        "online": state.online,
        "cursor": state.cursor,
        "pending_operations": len(pending),
        "open_conflicts": len(conflicts),
        "last_push_at": iso(state.last_push_at),
        "last_pull_at": iso(state.last_pull_at),
        "last_error": state.last_error,
        "next_retry_at": iso(min((p.next_attempt_at for p in pending), default=None)) if pending else None,
    }


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def resolve_conflict(db: Session, owner_id: str, conflict: SyncConflict, resolution: str,
                     settings: "Settings | None" = None) -> dict:
    """Решение владельца: 'local' — принять входящую версию, 'server' — оставить серверную."""
    if conflict.owner_id != owner_id:
        raise PermissionError("Конфликт принадлежит другому владельцу")
    if conflict.status != "open":
        return {"ok": False, "reason": "Конфликт уже закрыт"}
    if resolution not in ("local", "server"):
        raise ValueError("resolution должен быть 'local' или 'server'")

    in_entity = conflict.entity
    if resolution == "local":
        incoming = dict(conflict.incoming)
        operation = incoming.pop("operation", "upsert")
        payload = {k: v for k, v in incoming.items() if k in SYNC_FIELDS.get(in_entity, ())}
        # Локальная запись могла уйти вперёд/назад относительно серверной,
        # поэтому база — версия ИМЕННО локальной записи, иначе снова конфликт.
        model = ENTITY_MODELS.get(in_entity)
        local_obj = db.get(model, conflict.entity_id) if model else None
        local_version = int(local_obj.version) if local_obj is not None else 0
        result = apply_operation(
            db, owner_id, conflict.device_id or "conflict-resolution",
            entity=in_entity, entity_id=conflict.entity_id, operation=operation,
            payload=payload, base_version=local_version,
            op_id=f"resolve-{conflict.id}",
        )
    else:
        result = {"status": "kept_server", "entity_id": conflict.entity_id}

    # На клиенте (Desktop) выбор "local" должен уехать на HUB: иначе правка
    # останется только на ноутбуке. Ставим операцию в outbox с базовой версией
    # сервера — HUB примет её как обычный апдейт.
    if resolution == "local" and result.get("status") == "applied":
        if settings is None:
            from ..config import get_settings

            settings = get_settings()
        if not settings.is_hub:
            payload = {k: v for k, v in dict(conflict.incoming).items()
                       if k in SYNC_FIELDS.get(in_entity, ())}
            existing = db.execute(
                select(OutboxEntry).where(OutboxEntry.owner_id == owner_id,
                                          OutboxEntry.entity == in_entity,
                                          OutboxEntry.entity_id == conflict.entity_id)
            ).scalar_one_or_none()
            if existing is not None:
                # не плодим две операции на одну запись — обновляем очередь
                existing.payload = payload
                existing.operation = "upsert"
                existing.base_version = conflict.server_version
                existing.attempts = 0
                existing.next_attempt_at = utcnow()
                existing.last_error = ""
            else:
                enqueue_change(db, owner_id, in_entity, conflict.entity_id,
                               "upsert", payload, conflict.server_version)

    conflict.status = "resolved"
    conflict.resolution = resolution
    conflict.resolved_at = utcnow()
    db.flush()
    return {"ok": result.get("status") in ("applied", "kept_server"), "result": result,
            "conflict_id": conflict.id, "resolution": resolution}
