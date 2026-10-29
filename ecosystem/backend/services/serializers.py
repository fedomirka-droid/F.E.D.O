"""Сериализация сущностей для REST/Telegram."""
from __future__ import annotations

from ..db import iso
from ..models import CalendarEvent, Device, ScheduleEntry, Task


def task_public(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "status": task.status,
        "due_at": iso(task.due_at),
        "remind_at": iso(task.remind_at),
        "planned_minutes": task.planned_minutes,
        "actual_minutes": task.actual_minutes,
        "category": task.category,
        "started_at": iso(task.started_at),
        "completed_at": iso(task.completed_at),
        "version": task.version,
        "updated_at": iso(task.updated_at),
    }


def event_public(event: CalendarEvent) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "starts_at": iso(event.starts_at),
        "ends_at": iso(event.ends_at),
        "location": event.location,
        "category": event.category,
        "remind_at": iso(event.remind_at),
        "version": event.version,
        "updated_at": iso(event.updated_at),
    }


def schedule_public(entry: ScheduleEntry) -> dict:
    return {
        "id": entry.id,
        "group_name": entry.group_name,
        "date": entry.date,
        "slot": entry.slot,
        "start_time": entry.start_time,
        "end_time": entry.end_time,
        "subject": entry.subject,
        "teacher": entry.teacher,
        "room": entry.room,
        "lesson_type": entry.lesson_type,
        "source_file": entry.source_file,
        "source_sheet": entry.source_sheet,
        "version": entry.version,
    }


def device_summary(device: Device) -> dict:
    from .device_service import device_public

    return device_public(device)
