"""Расписание: импорт XLS/XLSX, занятия на сегодня/завтра."""
from __future__ import annotations

import re
from datetime import date, timedelta

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import DbDep, OwnerDep, SettingsDep, audit
from ..models import ScheduleEntry
from ..services import entities
from ..services.schedule_import import GROUP_DEFAULT, parse_schedule
from ..services.serializers import schedule_public

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

MAX_FILE_BYTES = 8 * 1024 * 1024
ALLOWED_EXT = (".xlsx", ".xls")
ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Стандартная сетка пар колледжа: номер пары определяется по времени начала.
BELL_SLOTS = (("08:30", 1), ("09:00", 1), ("10:10", 2), ("10:40", 2),
              ("11:50", 3), ("12:20", 3), ("13:40", 4), ("14:10", 4),
              ("15:20", 5), ("15:50", 5), ("17:00", 6), ("17:30", 6))


def slot_for_time(start_time: str) -> int:
    """Номер пары по времени начала; 0 — если время не задано."""
    value = (start_time or "").strip()
    if not value:
        return 0
    hour, _, minute = value.partition(":")
    try:
        minutes = int(hour) * 60 + int(minute or 0)
    except ValueError:
        return 0
    if minutes <= 0:
        return 0
    # ближайшая пара по времени начала (не позже 90 минут разницы)
    best, best_delta = 0, 91
    for bell, number in BELL_SLOTS:
        bh, bm = bell.split(":")
        delta = abs(minutes - (int(bh) * 60 + int(bm)))
        if delta < best_delta:
            best, best_delta = number, delta
    return best


class LessonIn(BaseModel):
    date: str = Field(max_length=10, description="ГГГГ-ММ-ДД")
    subject: str = Field(min_length=1, max_length=160)
    start_time: str = Field(default="", max_length=8, description="ЧЧ:ММ")
    end_time: str = Field(default="", max_length=8)
    teacher: str = Field(default="", max_length=120)
    room: str = Field(default="", max_length=64)
    lesson_type: str = Field(default="", max_length=32)
    group_name: str = Field(default=GROUP_DEFAULT, max_length=24)
    slot: int = Field(default=0, ge=0, le=12,
                      description="Номер пары; 0 — определить по времени начала")

    def cleaned(self) -> dict:
        data = self.model_dump()
        if not ISO_DAY_RE.match(data["date"]):
            raise HTTPException(status_code=422, detail="Дата должна быть в формате ГГГГ-ММ-ДД")
        try:
            date.fromisoformat(data["date"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Некорректная дата") from exc
        for key in ("start_time", "end_time"):
            value = data[key].strip()
            if value and not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", value):
                raise HTTPException(status_code=422,
                                    detail=f"Время {key} должно быть в формате ЧЧ:ММ")
            data[key] = value
        if not data["slot"]:
            data["slot"] = slot_for_time(data["start_time"])
        return data


@router.get("")
def list_entries(auth: OwnerDep, db: DbDep, day: str | None = Query(default=None),
                 group: str = Query(default=GROUP_DEFAULT)) -> dict:
    rows = db.execute(
        select(ScheduleEntry).where(ScheduleEntry.owner_id == auth.owner.id,
                                    ScheduleEntry.deleted_at.is_(None),
                                    ScheduleEntry.group_name == group)
        .order_by(ScheduleEntry.date, ScheduleEntry.slot)
    ).scalars().all()
    if day:
        rows = [r for r in rows if r.date == day]
    return {"entries": [schedule_public(e) for e in rows], "group": group}


def _day(db, owner_id: str, target: date, group: str) -> list[dict]:
    rows = db.execute(
        select(ScheduleEntry).where(ScheduleEntry.owner_id == owner_id,
                                    ScheduleEntry.deleted_at.is_(None),
                                    ScheduleEntry.group_name == group,
                                    ScheduleEntry.date == target.isoformat())
        .order_by(ScheduleEntry.slot, ScheduleEntry.start_time)
    ).scalars().all()
    return [schedule_public(e) for e in rows]


@router.post("")
def create_lesson(payload: LessonIn, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    """Ручное добавление занятия — когда Excel нет или нужна правка вручную."""
    entry = entities.create_entity(db, settings, auth.owner.id, "schedule", payload.cleaned(),
                                   device_id=auth.device.id if auth.device else "")
    audit(db, auth.owner.id, "schedule.create", target=entry.id, date=entry.date)
    return schedule_public(entry)


@router.patch("/{entry_id}")
def update_lesson(entry_id: str, payload: LessonIn, auth: OwnerDep, db: DbDep,
                  settings: SettingsDep) -> dict:
    row = db.get(ScheduleEntry, entry_id)
    if row is None or row.owner_id != auth.owner.id or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    entities.update_entity(db, settings, row, "schedule", payload.cleaned(),
                           device_id=auth.device.id if auth.device else "")
    audit(db, auth.owner.id, "schedule.update", target=row.id, date=row.date)
    return schedule_public(row)


@router.get("/today")
def today(auth: OwnerDep, db: DbDep, group: str = Query(default=GROUP_DEFAULT)) -> dict:
    target = date.today()
    return {"date": target.isoformat(), "group": group, "entries": _day(db, auth.owner.id, target, group)}


@router.get("/tomorrow")
def tomorrow(auth: OwnerDep, db: DbDep, group: str = Query(default=GROUP_DEFAULT)) -> dict:
    target = date.today() + timedelta(days=1)
    return {"date": target.isoformat(), "group": group, "entries": _day(db, auth.owner.id, target, group)}


@router.post("/import")
async def import_schedule(auth: OwnerDep, db: DbDep, settings: SettingsDep,
                          file: UploadFile = File(...),
                          group: str = Form(default=GROUP_DEFAULT),
                          date_override: str = Form(default=""),
                          replace_existing: bool = Form(default=True)) -> dict:
    filename = (file.filename or "schedule.xlsx").strip()
    if not filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(status_code=415, detail="Поддерживаются только файлы .xls и .xlsx")
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 8 МБ")
    if not data:
        raise HTTPException(status_code=422, detail="Пустой файл")
    try:
        result = parse_schedule(data, filename=filename, group=group,
                                date_override=date_override or None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not result.entries:
        return {"imported": 0, "warnings": result.warnings, "group": group,
                "sheets_scanned": result.sheets_scanned, "sheets_matched": result.sheets_matched}

    if replace_existing:
        existing = db.execute(
            select(ScheduleEntry).where(ScheduleEntry.owner_id == auth.owner.id,
                                        ScheduleEntry.deleted_at.is_(None),
                                        ScheduleEntry.group_name == group)
        ).scalars().all()
        dates = {e["date"] for e in result.entries}
        for row in existing:
            if row.date in dates:
                entities.delete_entity(db, settings, row, "schedule",
                                       device_id=auth.device.id if auth.device else "")

    created = 0
    for entry in result.entries:
        entry.pop("date_source", None)
        entities.create_entity(db, settings, auth.owner.id, "schedule", entry,
                               device_id=auth.device.id if auth.device else "")
        created += 1
    audit(db, auth.owner.id, "schedule.import", target=filename,
          lessons=created, group=group)
    return {"imported": created, "warnings": result.warnings, "group": group,
            "sheets_scanned": result.sheets_scanned, "sheets_matched": result.sheets_matched,
            "dates": sorted({e["date"] for e in result.entries})}


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    row = db.get(ScheduleEntry, entry_id)
    if row is None or row.owner_id != auth.owner.id:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    entities.delete_entity(db, settings, row, "schedule", device_id=auth.device.id if auth.device else "")
    return {"ok": True}
