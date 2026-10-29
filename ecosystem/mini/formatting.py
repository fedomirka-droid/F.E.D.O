"""Форматирование ответов бота (чистые функции — легко тестировать)."""
from __future__ import annotations

from datetime import datetime


def _time(entry: dict) -> str:
    start, end = entry.get("start_time") or "", entry.get("end_time") or ""
    return f"{start}–{end}" if start and end else (start or "—")


def format_lesson(entry: dict, index: int | None = None) -> str:
    prefix = f"{index}. " if index else ""
    parts = [f"{prefix}{_time(entry)} — {entry.get('subject') or 'занятие'}"]
    details = []
    if entry.get("teacher"):
        details.append(entry["teacher"])
    if entry.get("room"):
        details.append(entry["room"])
    if entry.get("lesson_type"):
        details.append(entry["lesson_type"])
    if details:
        parts.append(" • " + ", ".join(details))
    return "".join(parts)


def format_task(task: dict) -> str:
    icons = {"high": "🔴", "normal": "🟠", "low": "⚪️"}
    status = {"todo": "к выполнению", "in_progress": "в работе",
              "done": "готово", "skipped": "пропущено"}.get(task.get("status"), task.get("status"))
    line = f"{icons.get(task.get('priority'), '')} {task.get('title')} — {status}"
    if task.get("due_at"):
        line += f"\n   срок: {human_dt(task['due_at'])}"
    if task.get("planned_minutes"):
        line += f" · план {task['planned_minutes']} мин"
    if task.get("actual_minutes"):
        line += f" · факт {task['actual_minutes']} мин"
    return line


def human_dt(value: str | None) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.strftime("%d.%m %H:%M")


def format_today(data: dict) -> str:
    date = data.get("date", "")
    tasks = data.get("tasks") or []
    lessons = data.get("lessons") or []
    lines = [f"📅 <b>{date}</b>"]
    lines.append("\n<b>Занятия</b>")
    if lessons:
        lines += [format_lesson(entry, i) for i, entry in enumerate(lessons, 1)]
    else:
        lines.append("— занятий нет")
    lines.append("\n<b>Задачи</b>")
    if tasks:
        lines += [format_task(task) for task in tasks[:8]]
    else:
        lines.append("— активных задач нет")
    return "\n".join(lines)


def format_schedule(data: dict, title: str = "Расписание") -> str:
    entries = data.get("entries") or []
    head = f"🗓 <b>{title}</b> ({data.get('date', '')})"
    if not entries:
        return head + "\nЗанятий нет"
    return "\n".join([head] + [format_lesson(entry, i) for i, entry in enumerate(entries, 1)])


def format_devices(data: dict) -> str:
    devices = data.get("devices") or []
    if not devices:
        return "Устройства не зарегистрированы.\nДобавь их в Desktop → Устройства."
    icon = {"online": "🟢", "offline": "⚫️", "sleeping": "🌙", "revoked": "⛔️"}
    lines = ["<b>Устройства</b>"]
    for device in devices:
        line = f"{icon.get(device.get('status'), '·')} {device.get('name')} — {device.get('status')}"
        if device.get("ai_available"):
            line += " · AI доступен"
        lines.append(line)
    return "\n".join(lines)


def format_status(data: dict) -> str:
    usage = data.get("ai_usage") or {}
    lines = [
        "<b>Статус F.E.D.O.</b>",
        f"Устройств онлайн: {len(data.get('devices_online') or [])} из {data.get('devices_total', 0)}",
        f"AI: {data.get('ai_mode')}",
        f"Запросов сегодня: {usage.get('today_requests', 0)} "
        f"(облако {usage.get('today_cloud_requests', 0)})",
        f"Расход за месяц: {usage.get('month_cost', 0)}",
    ]
    if data.get("devices_online"):
        lines.append("Онлайн: " + ", ".join(data["devices_online"]))
    return "\n".join(lines)


def format_reminder(reminder: dict) -> str:
    task = reminder.get("task") or {}
    return f"🔔 Напоминание: <b>{task.get('title')}</b> (в {human_dt(reminder.get('at'))})"


def escape_html(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
