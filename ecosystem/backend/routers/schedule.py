"""Расписание: импорт XLS/XLSX, занятия на сегодня/завтра."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select

from ..deps import DbDep, OwnerDep, SettingsDep, audit
from ..models import ScheduleEntry
from ..services import entities
from ..services.schedule_import import GROUP_DEFAULT, parse_schedule
from ..services.serializers import schedule_public

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

MAX_FILE_BYTES = 8 * 1024 * 1024
ALLOWED_EXT = (".xlsx", ".xls")


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
