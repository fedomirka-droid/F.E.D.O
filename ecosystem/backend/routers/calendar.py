"""Календарь: события (синхронизируются)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import DbDep, OwnerDep, SettingsDep, audit
from ..models import CalendarEvent
from ..services import entities
from ..services.serializers import event_public
from ..services.sync_engine import parse_dt

router = APIRouter(prefix="/api/events", tags=["calendar"])


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    starts_at: str
    ends_at: str | None = None
    location: str = Field(default="", max_length=120)
    category: str = Field(default="", max_length=48)
    remind_at: str | None = None


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: str | None = None
    ends_at: str | None = None
    location: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=48)
    remind_at: str | None = None


def _owned(db, owner_id: str, event_id: str) -> CalendarEvent:
    event = db.get(CalendarEvent, event_id)
    if event is None or event.owner_id != owner_id or event.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    return event


@router.get("")
def list_events(auth: OwnerDep, db: DbDep,
                start: str | None = Query(default=None),
                end: str | None = Query(default=None)) -> dict:
    rows = db.execute(
        select(CalendarEvent).where(CalendarEvent.owner_id == auth.owner.id,
                                    CalendarEvent.deleted_at.is_(None))
        .order_by(CalendarEvent.starts_at)
    ).scalars().all()
    start_dt, end_dt = parse_dt(start), parse_dt(end)
    if start_dt:
        rows = [r for r in rows if r.starts_at >= start_dt]
    if end_dt:
        rows = [r for r in rows if r.starts_at <= end_dt]
    return {"events": [event_public(e) for e in rows]}


@router.post("")
def create_event(payload: EventCreate, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    if not parse_dt(payload.starts_at):
        raise HTTPException(status_code=422, detail="starts_at должен быть датой ISO-8601")
    event = entities.create_entity(db, settings, auth.owner.id, "event", payload.model_dump(),
                                   device_id=auth.device.id if auth.device else "")
    audit(db, auth.owner.id, "event.create", target=event.id)
    return event_public(event)


@router.patch("/{event_id}")
def update_event(event_id: str, payload: EventUpdate, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    event = _owned(db, auth.owner.id, event_id)
    entities.update_entity(db, settings, event, "event",
                           payload.model_dump(exclude_unset=True),
                           device_id=auth.device.id if auth.device else "")
    return event_public(event)


@router.delete("/{event_id}")
def delete_event(event_id: str, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    event = _owned(db, auth.owner.id, event_id)
    entities.delete_entity(db, settings, event, "event", device_id=auth.device.id if auth.device else "")
    audit(db, auth.owner.id, "event.delete", target=event.id)
    return {"ok": True}
