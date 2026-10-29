"""Пользовательские настройки (синхронизируются) и журнал аудита."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import iso
from ..deps import DbDep, OwnerDep, SettingsDep
from ..models import AuditLog, UserPreference
from ..services import entities

router = APIRouter(tags=["settings"])

ALLOWED_KEYS = ("theme", "ui_scale", "dashboard_layout", "notifications_enabled")


class PrefIn(BaseModel):
    key: str = Field(max_length=64)
    value: object


@router.get("/api/preferences")
def list_prefs(auth: OwnerDep, db: DbDep) -> dict:
    rows = db.execute(select(UserPreference).where(UserPreference.owner_id == auth.owner.id,
                                                   UserPreference.deleted_at.is_(None))).scalars().all()
    return {"preferences": {row.key: (row.value or {}).get("v") for row in rows}}


@router.put("/api/preferences")
def set_pref(payload: PrefIn, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    row = entities.set_preference(db, settings, auth.owner.id, payload.key, payload.value,
                                  device_id=auth.device.id if auth.device else "")
    return {"key": row.key, "value": (row.value or {}).get("v")}


@router.get("/api/audit")
def audit_log(auth: OwnerDep, db: DbDep, limit: int = 100) -> dict:
    rows = db.execute(select(AuditLog).where(AuditLog.owner_id == auth.owner.id)
                      .order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 500))).scalars().all()
    return {"entries": [{
        "id": row.id, "actor": row.actor, "action": row.action, "target": row.target,
        "detail": row.detail, "created_at": iso(row.created_at),
    } for row in rows]}
