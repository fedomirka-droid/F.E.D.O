"""Sync API: push (идемпотентно), pull (курсор), конфликты, ручной запуск."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import Settings
from ..deps import DbDep, OwnerDep, SettingsDep, SyncDep
from ..models import SyncConflict
from ..services import sync_engine, sync_worker
from ..services.sync_engine import iso

router = APIRouter(prefix="/api/sync", tags=["sync"])


class Operation(BaseModel):
    op_id: str = Field(min_length=6, max_length=64)
    entity: str
    entity_id: str
    operation: str = "upsert"
    payload: dict = Field(default_factory=dict)
    base_version: int = 0


class PushRequest(BaseModel):
    operations: list[Operation] = Field(default_factory=list, max_length=500)


class ResolveRequest(BaseModel):
    resolution: str  # local | server


@router.post("/push")
def push(payload: PushRequest, principal: SyncDep, db: DbDep, settings: SettingsDep) -> dict:
    results = sync_engine.push_operations(
        db, principal.owner_id, principal.device_id or "session-device",
        [op.model_dump() for op in payload.operations],
    )
    return {"results": results, "server_role": settings.role}


@router.get("/pull")
def pull(principal: SyncDep, db: DbDep, cursor: int = Query(default=0, ge=0),
         exclude_device: str = Query(default=""), limit: int = Query(default=500, ge=1, le=1000)) -> dict:
    return sync_engine.pull_changes(db, principal.owner_id, cursor=cursor,
                                    exclude_device=exclude_device or None, limit=limit)


@router.get("/status")
def status(auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    data = sync_engine.sync_status(db, auth.owner.id)
    data.update({
        "role": settings.role,
        "hub_url": settings.hub_url,
        "sync_enabled": settings.sync_enabled,
        "hub_configured": bool(settings.hub_url),
    })
    return data


@router.post("/run")
def run_now(auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    return sync_worker.run_sync(db, settings, auth.owner.id)


@router.get("/conflicts")
def conflicts(auth: OwnerDep, db: DbDep, include_resolved: bool = False) -> dict:
    query = select(SyncConflict).where(SyncConflict.owner_id == auth.owner.id)
    if not include_resolved:
        query = query.where(SyncConflict.status == "open")
    rows = db.execute(query.order_by(SyncConflict.created_at.desc()).limit(200)).scalars().all()
    return {"conflicts": [{
        "id": row.id, "entity": row.entity, "entity_id": row.entity_id,
        "base_version": row.base_version, "server_version": row.server_version,
        "incoming": row.incoming, "server": row.server, "status": row.status,
        "resolution": row.resolution, "created_at": iso(row.created_at),
    } for row in rows]}


@router.post("/conflicts/{conflict_id}/resolve")
def resolve(conflict_id: str, payload: ResolveRequest, auth: OwnerDep, db: DbDep,
            settings: SettingsDep) -> dict:
    conflict = db.get(SyncConflict, conflict_id)
    if conflict is None or conflict.owner_id != auth.owner.id:
        raise HTTPException(status_code=404, detail="Конфликт не найден")
    try:
        return sync_engine.resolve_conflict(db, auth.owner.id, conflict, payload.resolution,
                                            settings=settings)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/outbox")
def outbox(auth: OwnerDep, db: DbDep) -> dict:
    from ..models import OutboxEntry

    rows = db.execute(select(OutboxEntry).where(OutboxEntry.owner_id == auth.owner.id)
                      .order_by(OutboxEntry.id)).scalars().all()
    return {"outbox": [{
        "op_id": row.op_id, "entity": row.entity, "entity_id": row.entity_id,
        "operation": row.operation, "base_version": row.base_version,
        "attempts": row.attempts, "last_error": row.last_error,
        "next_attempt_at": iso(row.next_attempt_at),
    } for row in rows]}
