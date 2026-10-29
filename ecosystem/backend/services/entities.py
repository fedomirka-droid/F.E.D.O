"""Единая точка записи синхронизируемых сущностей.

Любое изменение через API:
  * поднимает version и updated_at;
  * на HUB → пишет change_log (источник для pull);
  * на Desktop → кладёт операцию в outbox (для push), схлопывая повторы
    по одной сущности, чтобы не копить версии в офлайне.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..models import ChangeLog, OutboxEntry, UserPreference
from .sync_engine import ENTITY_MODELS, SYNC_FIELDS, entity_to_dict, normalize_value


def _clean(kind: str, data: dict) -> dict:
    return {k: normalize_value(k, v) for k, v in data.items() if k in SYNC_FIELDS[kind]}


def _register_change(db: Session, settings: Settings, owner_id: str, kind: str, obj: Any,
                     operation: str, device_id: str, base_version: int) -> None:
    payload = entity_to_dict(obj)
    if settings.is_hub:
        db.add(ChangeLog(owner_id=owner_id, entity=kind, entity_id=obj.id, version=obj.version,
                         operation=operation, payload=payload, device_id=device_id or None))
        db.flush()
        return
    existing = db.execute(
        select(OutboxEntry).where(OutboxEntry.owner_id == owner_id,
                                  OutboxEntry.entity == kind,
                                  OutboxEntry.entity_id == obj.id)
    ).scalar_one_or_none()
    if existing is not None:
        existing.payload = payload
        existing.operation = operation
        existing.attempts = 0
        existing.next_attempt_at = utcnow()
        existing.last_error = ""
    else:
        from .sync_engine import enqueue_change

        enqueue_change(db, owner_id, kind, obj.id, operation, payload, base_version)


def create_entity(db: Session, settings: Settings, owner_id: str, kind: str,
                  data: dict, device_id: str = "") -> Any:
    model = ENTITY_MODELS[kind]
    values = _clean(kind, data)
    obj = model(owner_id=owner_id, version=1, origin_device=device_id or None,
                created_at=utcnow(), updated_at=utcnow(), **values)
    if "id" in data and data["id"]:
        obj.id = str(data["id"])
    db.add(obj)
    db.flush()
    _register_change(db, settings, owner_id, kind, obj, "upsert", device_id, base_version=0)
    return obj


def update_entity(db: Session, settings: Settings, obj: Any, kind: str, data: dict,
                  device_id: str = "") -> Any:
    base_version = obj.version
    for field, value in _clean(kind, data).items():
        setattr(obj, field, value)
    obj.version = base_version + 1
    obj.updated_at = utcnow()
    obj.deleted_at = None
    obj.origin_device = device_id or obj.origin_device
    db.flush()
    _register_change(db, settings, owner_id=obj.owner_id, kind=kind, obj=obj,
                     operation="upsert", device_id=device_id, base_version=base_version)
    return obj


def delete_entity(db: Session, settings: Settings, obj: Any, kind: str,
                  device_id: str = "") -> Any:
    base_version = obj.version
    obj.deleted_at = utcnow()
    obj.version = base_version + 1
    obj.updated_at = utcnow()
    obj.origin_device = device_id or obj.origin_device
    db.flush()
    _register_change(db, settings, owner_id=obj.owner_id, kind=kind, obj=obj,
                     operation="delete", device_id=device_id, base_version=base_version)
    return obj


def get_preference(db: Session, owner_id: str, key: str) -> Any:
    return db.execute(
        select(UserPreference).where(UserPreference.owner_id == owner_id, UserPreference.key == key)
    ).scalar_one_or_none()


def set_preference(db: Session, settings: Settings, owner_id: str, key: str,
                   value: Any, device_id: str = "") -> UserPreference:
    row = get_preference(db, owner_id, key)
    if row is None:
        return create_entity(db, settings, owner_id, "preference",
                             {"key": key, "value": {"v": value}}, device_id)
    return update_entity(db, settings, row, "preference", {"value": {"v": value}}, device_id)
