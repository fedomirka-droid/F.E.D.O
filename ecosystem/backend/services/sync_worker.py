"""Процесс синхронизации Desktop ↔ HUB (push очереди + pull изменений).

Запускается:
  * вручную из UI (POST /api/sync/run);
  * фоновым потоком в lifespan Desktop (FEDO_SYNC_ENABLED=1 + FEDO_HUB_URL).
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import iso, utcnow
from ..models import Device, OutboxEntry, SyncConflict
from .sync_engine import (
    ENTITY_MODELS,
    apply_remote_change,
    get_sync_state,
    mark_failed,
    parse_dt,
    pending_operations,
)

logger = logging.getLogger("fedo.sync")


def local_device_id(db: Session) -> str:
    device = db.execute(select(Device).where(Device.kind == "desktop")).scalars().first()
    return device.id if device else ""


def run_sync(db: Session, settings: Settings, owner_id: str,
             hub_url: str | None = None, device_token: str | None = None,
             client: httpx.Client | None = None) -> dict:
    """Один цикл синхронизации: push → pull. Возвращает отчёт."""
    hub = (hub_url if hub_url is not None else settings.hub_url).rstrip("/")
    token = device_token if device_token is not None else getattr(settings, "sync_device_token", "")
    state = get_sync_state(db, owner_id)
    if settings.is_hub:
        return {"ok": False, "reason": "HUB не синхронизируется сам с собой"}
    if not hub or not token:
        state.online = False
        state.last_error = "HUB не настроен"
        return {"ok": False, "reason": "HUB не настроен (нужны адрес и токен устройства)",
                "pushed": 0, "pulled": 0, "conflicts": 0}

    owns_client = client is None
    http = client or httpx.Client(timeout=settings.sync_request_timeout)
    headers = {"X-Device-Token": token, "Content-Type": "application/json"}
    device_id = local_device_id(db)
    pushed = applied = conflicts = pulled = 0
    try:
        pending = pending_operations(db, owner_id, limit=200)
        if pending:
            payload = {"operations": [{
                "op_id": item.op_id, "entity": item.entity, "entity_id": item.entity_id,
                "operation": item.operation, "payload": item.payload,
                "base_version": item.base_version,
            } for item in pending]}
            resp = http.post(f"{hub}/api/sync/push", json=payload, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"HUB push HTTP {resp.status_code}")
            for result in resp.json().get("results", []):
                pushed += 1
                entry = db.execute(
                    select(OutboxEntry).where(OutboxEntry.op_id == result.get("op_id"))
                ).scalar_one_or_none()
                if entry is None:
                    continue
                status = result.get("status")
                if status == "applied":
                    model = ENTITY_MODELS.get(entry.entity)
                    obj = db.get(model, entry.entity_id) if model else None
                    if obj is not None and result.get("version"):
                        obj.version = int(result["version"])
                        obj.updated_at = parse_dt(result.get("updated_at")) or utcnow()
                    db.delete(entry)
                    applied += 1
                elif status == "conflict":
                    db.add(SyncConflict(
                        id=result.get("conflict_id") or None,
                        owner_id=owner_id, entity=entry.entity, entity_id=entry.entity_id,
                        base_version=int(result.get("base_version") or entry.base_version),
                        server_version=int(result.get("server_version") or 0),
                        incoming={**entry.payload, "operation": entry.operation},
                        server=result.get("server") or {}, device_id=device_id,
                    ))
                    db.delete(entry)  # не ретраим: версия конфликтует, нужно решение владельца
                    conflicts += 1
                else:
                    mark_failed(db, entry, str(result.get("reason") or status or "unknown"))
            state.last_push_at = utcnow()
            db.flush()

        resp = http.get(f"{hub}/api/sync/pull", headers=headers,
                        params={"cursor": state.cursor, "exclude_device": device_id})
        if resp.status_code >= 400:
            raise RuntimeError(f"HUB pull HTTP {resp.status_code}")
        data = resp.json()
        for change in data.get("changes", []):
            outcome = apply_remote_change(db, owner_id, change)
            if outcome == "applied":
                pulled += 1
            elif outcome == "conflict":
                conflicts += 1
        state.cursor = int(data.get("cursor") or state.cursor)
        state.last_pull_at = utcnow()
        state.online = True
        state.last_error = ""
        db.flush()
    except Exception as exc:
        state.online = False
        state.last_error = str(exc)[:255]
        for entry in db.execute(
            select(OutboxEntry).where(OutboxEntry.owner_id == owner_id)
        ).scalars().all():
            if entry.attempts < 12:
                mark_failed(db, entry, str(exc))
        logger.warning("sync failed: %s", exc)
        return {"ok": False, "reason": str(exc), "pushed": pushed, "applied": applied,
                "pulled": pulled, "conflicts": conflicts, "last_error": state.last_error}
    finally:
        if owns_client:
            http.close()

    return {"ok": True, "pushed": pushed, "applied": applied, "pulled": pulled,
            "conflicts": conflicts, "cursor": state.cursor, "online": state.online,
            "synced_at": iso(utcnow())}
