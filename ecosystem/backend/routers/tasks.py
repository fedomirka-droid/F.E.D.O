"""Задачи: CRUD, статусы, учёт времени, напоминания."""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import iso, utcnow
from ..deps import DbDep, OwnerDep, SettingsDep, audit
from ..models import Task
from ..services import entities
from ..services.serializers import task_public
from ..services.sync_engine import normalize_value, parse_dt

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

Priority = Literal["low", "normal", "high"]
Status = Literal["todo", "in_progress", "done", "skipped"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    priority: Priority = "normal"
    status: Status = "todo"
    due_at: str | None = None
    remind_at: str | None = None
    planned_minutes: int = Field(default=0, ge=0, le=100000)
    category: str = Field(default="", max_length=48)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    priority: Priority | None = None
    status: Status | None = None
    due_at: str | None = None
    remind_at: str | None = None
    planned_minutes: int | None = Field(default=None, ge=0, le=100000)
    actual_minutes: int | None = Field(default=None, ge=0, le=100000)
    category: str | None = Field(default=None, max_length=48)


class TimeLog(BaseModel):
    minutes: int = Field(ge=1, le=600)


def _owned_task(db, owner_id: str, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.owner_id != owner_id or task.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task


@router.get("")
def list_tasks(auth: OwnerDep, db: DbDep,
               status: str | None = Query(default=None),
               include_done: bool = True,
               limit: int = Query(default=200, ge=1, le=500)) -> dict:
    query = select(Task).where(Task.owner_id == auth.owner.id, Task.deleted_at.is_(None))
    if status:
        query = query.where(Task.status == status)
    elif not include_done:
        query = query.where(Task.status.not_in(("done", "skipped")))
    rows = db.execute(query.order_by(Task.due_at.is_(None), Task.due_at, Task.created_at).limit(limit)).scalars().all()
    return {"tasks": [task_public(t) for t in rows]}


@router.get("/today")
def tasks_today(auth: OwnerDep, db: DbDep) -> dict:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    rows = db.execute(
        select(Task).where(Task.owner_id == auth.owner.id, Task.deleted_at.is_(None))
    ).scalars().all()
    today = [t for t in rows if (t.due_at and start <= t.due_at < end) or t.status == "in_progress"
             or (t.due_at and t.due_at < start and t.status not in ("done", "skipped"))]
    return {"tasks": [task_public(t) for t in today], "date": start.date().isoformat()}


@router.post("")
def create_task(payload: TaskCreate, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    task = entities.create_entity(db, settings, auth.owner.id, "task", payload.model_dump(),
                                  device_id=auth.device.id if auth.device else "")
    audit(db, auth.owner.id, "task.create", target=task.id, title=task.title)
    return task_public(task)


@router.get("/{task_id}")
def get_task(task_id: str, auth: OwnerDep, db: DbDep) -> dict:
    return task_public(_owned_task(db, auth.owner.id, task_id))


@router.patch("/{task_id}")
def update_task(task_id: str, payload: TaskUpdate, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    task = _owned_task(db, auth.owner.id, task_id)
    data = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    if "status" in data and data["status"] == "done":
        data.setdefault("completed_at", utcnow())
    entities.update_entity(db, settings, task, "task", data,
                           device_id=auth.device.id if auth.device else "")
    return task_public(task)


@router.delete("/{task_id}")
def delete_task(task_id: str, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    task = _owned_task(db, auth.owner.id, task_id)
    entities.delete_entity(db, settings, task, "task", device_id=auth.device.id if auth.device else "")
    audit(db, auth.owner.id, "task.delete", target=task.id)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Действия (используются и из Telegram-бота)
# --------------------------------------------------------------------------- #
def apply_action(db, settings, owner_id: str, task: Task, action: str,
                 minutes: int = 0, device_id: str = "") -> Task:
    now = utcnow()
    data: dict = {}
    if action == "start":
        data = {"status": "in_progress", "started_at": now}
    elif action == "complete":
        data = {"status": "done", "completed_at": now}
    elif action == "skip":
        data = {"status": "skipped"}
    elif action == "reopen":
        data = {"status": "todo", "completed_at": None}
    elif action == "extend":
        data = {"planned_minutes": (task.planned_minutes or 0) + (minutes or 15)}
    elif action == "time":
        data = {"actual_minutes": (task.actual_minutes or 0) + max(minutes, 1)}
    else:
        raise ValueError(f"Неизвестное действие: {action}")
    return entities.update_entity(db, settings, task, "task", data, device_id=device_id)


@router.post("/{task_id}/action/{action}")
def task_action(task_id: str, action: str, auth: OwnerDep, db: DbDep, settings: SettingsDep,
                minutes: int = Query(default=0, ge=0, le=600)) -> dict:
    task = _owned_task(db, auth.owner.id, task_id)
    try:
        apply_action(db, settings, auth.owner.id, task, action, minutes,
                     device_id=auth.device.id if auth.device else "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, auth.owner.id, f"task.{action}", target=task.id, minutes=minutes)
    return task_public(task)


@router.post("/{task_id}/time")
def log_time(task_id: str, payload: TimeLog, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    task = _owned_task(db, auth.owner.id, task_id)
    apply_action(db, settings, auth.owner.id, task, "time", payload.minutes,
                 device_id=auth.device.id if auth.device else "")
    return task_public(task)


@router.get("/reminders/due")
def due_reminders(auth: OwnerDep, db: DbDep, window_minutes: int = Query(default=30, ge=1, le=1440)) -> dict:
    now = utcnow()
    horizon = now + timedelta(minutes=window_minutes)
    rows = db.execute(select(Task).where(Task.owner_id == auth.owner.id, Task.deleted_at.is_(None))).scalars().all()
    due = [task_public(t) for t in rows
           if t.remind_at and now - timedelta(minutes=5) <= t.remind_at <= horizon
           and t.status not in ("done", "skipped")]
    return {"reminders": due, "now": iso(now)}
