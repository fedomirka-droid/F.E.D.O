"""Student Edition: совместимый слой.

Исходников Student Edition MVP в репозитории нет, поэтому интеграция помечена
как заблокированная — но слой вокруг неё настоящий:

  * профиль студента (группа, специальность, курс, семестр, зачётка);
  * сканер того, что реально лежит на диске (каталог, архив, SQLite-база);
  * импортёр чужой SQLite-базы: задачи, занятия, профиль. Работает на реальных
    данных, идемпотентен (журнал LegacyImportRecord), поддерживает dry-run;
  * повторный импорт обновляет записи, а не плодит дубликаты.

Сканер намеренно исключает собственную базу Ecosystem: иначе пользователь
«импортировал» бы сам себя и получил дубли задач.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import utcnow
from ..models import LegacyImportRecord, ScheduleEntry, StudentProfile, Task
from . import entities

PROFILE_NAMESPACE = uuid.UUID("6f1c4a9e-6f3d-5a4b-9c2e-1d7b8a0c3e51")
# Корень репозитория: ecosystem/backend/services/student.py → вверх три уровня.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Что ищем и что именно даёт каждая находка. Порядок = приоритет.
EXPECTED_ARTIFACTS: tuple[dict[str, str], ...] = (
    {"path": "student_edition/", "kind": "dir", "why": "исходники Student Edition (полная интеграция)"},
    {"path": "student_edition/backend/models.py", "kind": "file", "why": "точный маппинг полей"},
    {"path": "student_edition/backend/main.py", "kind": "file", "why": "сохранение прежних entry points"},
    {"path": "student_edition/frontend/", "kind": "dir", "why": "перенос экранов в Desktop"},
    {"path": "student_edition.db", "kind": "file", "why": "данные пользователя (импорт)"},
    {"path": "data/student_edition.db", "kind": "file", "why": "данные пользователя (импорт)"},
    {"path": "F.E.D.O-Student-Edition-MVP.zip", "kind": "file", "why": "архив с кодом и данными"},
)

# Таблицы, по которым узнаём студенческую базу (а не любую SQLite).
LEGACY_TASK_TABLES = ("tasks", "task", "todos", "todo")
LEGACY_LESSON_TABLES = ("lessons", "lesson", "schedule", "timetable")
LEGACY_PROFILE_TABLES = ("student_profile", "students", "profile")
LEGACY_USER_TABLES = ("users", "user", "accounts")
SIGNATURE_TABLES = ("lessons", "student_profile", "students", "timetable", "schedule")
# Таблицы собственного Ecosystem — такую базу импортировать нельзя.
ECOSYSTEM_TABLES = {"owners", "devices", "outbox", "change_log", "sync_operations"}

# Альтернативные имена колонок в чужой базе — единственное место правок схемы.
TASK_FIELD_ALIASES = {
    "title": ("title", "name", "subject", "task", "what"),
    "description": ("description", "desc", "details", "note", "notes"),
    "priority": ("priority", "prio", "importance", "level"),
    "status": ("status", "state", "done", "is_done", "completed"),
    "due_at": ("due_at", "due_date", "deadline", "due", "date_end", "finish_at"),
    "remind_at": ("remind_at", "reminder", "remind", "alert_at"),
    "planned_minutes": ("planned_minutes", "estimate", "planned", "duration"),
    "actual_minutes": ("actual_minutes", "spent", "elapsed", "time_spent"),
    "category": ("category", "tag", "type_tag"),
}
LESSON_FIELD_ALIASES = {
    "date": ("date", "day", "lesson_date", "study_date"),
    "start_time": ("start_time", "start", "time_start", "starts_at", "begin"),
    "end_time": ("end_time", "end", "time_end", "ends_at", "finish"),
    "subject": ("subject", "lesson", "discipline", "name", "title"),
    "teacher": ("teacher", "professor", "lecturer", "prepod"),
    "room": ("room", "cabinet", "auditorium", "class"),
    "lesson_type": ("lesson_type", "type", "kind", "format"),
    "group_name": ("group_name", "group", "group_code", "group_id"),
}
PROFILE_FIELD_ALIASES = {
    "group_name": ("group_name", "group", "group_code", "group_id"),
    "college": ("college", "institution", "university", "school"),
    "specialty": ("specialty", "speciality", "major", "program"),
    "course": ("course", "year", "course_number"),
    "semester": ("semester", "term"),
    "study_form": ("study_form", "form", "education_form"),
    "student_card": ("student_card", "card", "student_id", "record_book"),
    "notes": ("notes", "note", "comment"),
}

STATUS_ALIASES = {
    "done": "done", "completed": "done", "complete": "done", "finished": "done",
    "готово": "done", "выполнено": "done",
    "doing": "in_progress", "in_progress": "in_progress", "progress": "in_progress",
    "active": "in_progress", "в работе": "in_progress",
    "cancelled": "skipped", "canceled": "skipped", "skipped": "skipped",
    "отменено": "skipped", "пропущено": "skipped",
    "new": "todo", "todo": "todo", "planned": "todo", "pending": "todo", "": "todo",
}
PRIORITY_ALIASES = {
    "low": "low", "низкий": "low", "1": "low",
    "normal": "normal", "medium": "normal", "средний": "normal", "2": "normal",
    "high": "high", "высокий": "high", "3": "high",
    "critical": "critical", "urgent": "critical", "критичный": "critical", "4": "critical",
}


def profile_id(owner_id: str) -> str:
    """Детерминированный id профиля: одинаков на всех узлах владельца."""
    return str(uuid.uuid5(PROFILE_NAMESPACE, owner_id))


# --------------------------------------------------------------------------- #
# Сканирование источников
# --------------------------------------------------------------------------- #
def _table_names(con: sqlite3.Connection) -> list[str]:
    try:
        return [row[0] for row in con.execute(
            "select name from sqlite_master where type='table'").fetchall()]
    except sqlite3.Error:
        return []


def inspect_database(path: Path) -> dict | None:
    """Разобрать SQLite-файл: какие студенческие таблицы в нём есть.

    Возвращает None, если файл не SQLite или это база самого Ecosystem.
    """
    if not path.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        tables = _table_names(con)
    finally:
        con.close()
    if not tables:
        return None
    if ECOSYSTEM_TABLES & set(tables):
        return None
    legacy = [t for t in tables if t in LEGACY_TASK_TABLES + LEGACY_LESSON_TABLES
              + LEGACY_PROFILE_TABLES + LEGACY_USER_TABLES]
    signature = [t for t in tables if t in SIGNATURE_TABLES]
    if not signature and not legacy:
        return None
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "tables": tables,
        "legacy_tables": legacy,
        "signature_tables": signature,
    }


def _candidate_paths(roots: Iterable[Path]) -> list[Path]:
    names = ("student_edition.db", "F.E.D.O-Student-Edition.db", "fedo_student.db",
             "students.db", "student.db", "study.db")
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for name in names:
            for base in (root, root / "data"):
                candidate = base / name
                if candidate.is_file() and candidate not in found:
                    found.append(candidate)
    return found


def detect_legacy(roots: Iterable[Path | str] | None = None) -> dict:
    """Что найдено на диске. Возвращает факты, а не догадки."""
    base = Path(PROJECT_ROOT)
    search_roots = [Path(r) for r in roots] if roots is not None else [base]
    found: list[dict[str, str]] = []
    for artifact in EXPECTED_ARTIFACTS:
        target = base / artifact["path"]
        exists = target.is_dir() if artifact["kind"] == "dir" else target.is_file()
        if exists:
            found.append({**artifact, "absolute": str(target)})

    databases: list[dict[str, Any]] = []
    for candidate in _candidate_paths(search_roots):
        info = inspect_database(candidate)
        if info is not None and info not in databases:
            databases.append(info)

    state = "adapter_ready" if databases else "blocked"
    sources_present = (base / "student_edition").is_dir()
    found_paths = {item["path"] for item in found}
    return {
        "state": state,
        "integration": "blocked" if state == "blocked" else "data_available",
        "root": str(base),
        "root_dir_present": sources_present,
        "sources_present": sources_present,
        "found": found,
        "missing": [a["path"] for a in EXPECTED_ARTIFACTS if a["path"] not in found_paths],
        "databases": databases,
        "search_roots": [str(r) for r in search_roots],
    }


def integration_status(db: Session, owner_id: str) -> dict:
    """Сводка: что есть, чего нет, что уже импортировано."""
    detection = detect_legacy()
    profile = find_profile(db, owner_id)
    imported_tasks = db.execute(
        select(Task).where(Task.owner_id == owner_id,
                          Task.origin_device == "legacy-import")).scalars().all()
    imported_schedule = db.execute(
        select(ScheduleEntry).where(ScheduleEntry.owner_id == owner_id,
                                   ScheduleEntry.origin_device == "legacy-import")).scalars().all()
    return {
        **detection,
        "profile": profile_public(profile) if profile else None,
        "imported": {"tasks": len(imported_tasks), "schedule": len(imported_schedule),
                     "profile": bool(profile and profile.source == "legacy_import")},
        "blocked_reason": (
            None if detection["state"] != "blocked" else
            "Исходники/архив Student Edition MVP отсутствуют в репозитории"
        ),
    }


# --------------------------------------------------------------------------- #
# Профиль
# --------------------------------------------------------------------------- #
def find_profile(db: Session, owner_id: str) -> StudentProfile | None:
    """Найти профиль владельца, не создавая его.

    Первый путь — детерминированный id. Второй нужен, когда запись пришла
    синхронизацией с другого узла: там id считается от его собственного owner_id.
    """
    profile = db.get(StudentProfile, profile_id(owner_id))
    if profile is None:
        profile = db.execute(
            select(StudentProfile).where(StudentProfile.owner_id == owner_id)
        ).scalars().first()
    return profile


def get_or_create_profile(db: Session, owner_id: str) -> StudentProfile:
    """Профиль владельца; создаётся при первом обращении."""
    profile = find_profile(db, owner_id)
    if profile is None:
        profile = StudentProfile(
            id=profile_id(owner_id), owner_id=owner_id, group_name="ИС-21", version=1,
            created_at=utcnow(), updated_at=utcnow(),
        )
        db.add(profile)
        db.flush()
    return profile


def update_profile(db: Session, owner_id: str, data: dict,
                   settings: Settings | None = None, device_id: str = "") -> StudentProfile:
    """Обновить профиль. Через outbox, чтобы изменение уехало на HUB."""
    profile = get_or_create_profile(db, owner_id)
    payload = {key: value for key, value in data.items() if value is not None}
    if not payload:
        return profile
    if settings is None:
        settings = get_settings()
    if "source" not in payload:
        payload["source"] = "manual"
    entities.update_entity(db, settings, profile, "student_profile", payload,
                           device_id=device_id)
    return profile


def profile_public(profile: StudentProfile) -> dict:
    return {
        "id": profile.id,
        "group_name": profile.group_name,
        "college": profile.college,
        "specialty": profile.specialty,
        "course": profile.course,
        "semester": profile.semester,
        "study_form": profile.study_form,
        "student_card": profile.student_card,
        "notes": profile.notes,
        "source": profile.source,
        "version": profile.version,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


# --------------------------------------------------------------------------- #
# Импорт чужой SQLite-базы
# --------------------------------------------------------------------------- #
def _bucket() -> dict[str, int]:
    return {"created": 0, "updated": 0, "skipped": 0}


def _pick(row: dict, aliases: dict[str, tuple[str, ...]], field: str) -> Any:
    for column in aliases.get(field, ()):
        if column in row and row[column] not in (None, ""):
            return row[column]
    return None


def _normalize_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 1e11:
            stamp /= 1000.0
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text.replace("Z", ""), fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def _normalize_dt(value: Any) -> str | None:
    day = _normalize_date(value)
    return f"{day}T00:00:00" if day else None


def _normalize_status(value: Any) -> str:
    if isinstance(value, bool):
        return "done" if value else "todo"
    text = str(value or "").strip().lower()
    if text in STATUS_ALIASES:
        return STATUS_ALIASES[text]
    if text in ("1", "true", "yes"):
        return "done"
    return "todo"


def _normalize_priority(value: Any) -> str:
    text = str(value if value is not None else "").strip().lower()
    return PRIORITY_ALIASES.get(text, "normal")


def _as_int(value: Any) -> int | None:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _read_rows(con: sqlite3.Connection, table: str) -> list[dict]:
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(f'select * from "{table}"').fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _checksum(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str)
                          .encode("utf-8")).hexdigest()[:32]


def _first_table(tables: list[str], candidates: tuple[str, ...]) -> str | None:
    return next((t for t in candidates if t in tables), None)


def _journal(db: Session, owner_id: str, source: Path, kind: str,
             key: str) -> LegacyImportRecord | None:
    return db.execute(
        select(LegacyImportRecord).where(LegacyImportRecord.owner_id == owner_id,
                                        LegacyImportRecord.source_path == str(source),
                                        LegacyImportRecord.kind == kind,
                                        LegacyImportRecord.source_key == key)
    ).scalars().first()


def _note_import(db: Session, owner_id: str, source: Path, kind: str, key: str,
                 target_id: str, payload: dict) -> None:
    db.add(LegacyImportRecord(
        owner_id=owner_id, source_path=str(source), kind=kind, source_key=key,
        target_id=target_id, checksum=_checksum(payload), imported_at=utcnow()))


def import_legacy(db: Session, owner_id: str, source: str,
                  dry_run: bool = False, settings: Settings | None = None,
                  device_id: str = "legacy-import") -> dict:
    """Перенести задачи/занятия/профиль из SQLite Student Edition."""
    path = Path(source)
    report: dict[str, Any] = {
        "ok": True, "reason": "", "source": str(path), "dry_run": dry_run,
        "tasks": _bucket(), "schedule": _bucket(),
        "profile": {"created": 0, "updated": 0, "skipped": 0},
        "users": {"matched": 0, "created": 0},
        "warnings": [], "tables": [],
    }
    if not path.is_file():
        return {**report, "ok": False, "reason": "Файл базы не найден"}
    with path.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            return {**report, "ok": False, "reason": "Это не SQLite-база"}

    info = inspect_database(path)
    if info is None:
        return {**report, "ok": False,
                "reason": ("Это база самого Ecosystem (есть таблицы owners/devices/outbox) "
                           "или неизвестный формат. Импорт собственных данных запрещён.")}
    report["tables"] = info["tables"]

    if settings is None:
        settings = get_settings()
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return {**report, "ok": False, "reason": f"Не удалось открыть базу: {exc}"}
    try:
        tables = info["tables"]
        _import_tasks(db, con, owner_id, path, settings, device_id, report, tables)
        _import_lessons(db, con, owner_id, path, settings, device_id, report, tables)
        _match_users(db, owner_id, con, report, tables)
        _import_profile(db, con, owner_id, path, settings, device_id, report, tables)
    except sqlite3.DatabaseError as exc:
        return {**report, "ok": False, "reason": f"Ошибка чтения базы: {exc}"}
    finally:
        con.close()

    if dry_run:
        # ничего не фиксируем: отчёт остаётся, данные — нет
        db.rollback()
    return report


def _import_tasks(db, con, owner_id, path, settings, device_id, report, tables) -> None:
    table = _first_table(tables, LEGACY_TASK_TABLES)
    if table is None:
        return
    bucket = report["tasks"]
    seen: set[str] = set()
    for index, row in enumerate(_read_rows(con, table)):
        title = _pick(row, TASK_FIELD_ALIASES, "title")
        if not title:
            bucket["skipped"] += 1
            continue
        payload: dict[str, Any] = {
            "title": str(title).strip()[:200],
            "description": str(_pick(row, TASK_FIELD_ALIASES, "description") or "")[:8000],
            "priority": _normalize_priority(_pick(row, TASK_FIELD_ALIASES, "priority")),
            "status": _normalize_status(_pick(row, TASK_FIELD_ALIASES, "status")),
            "due_at": _normalize_dt(_pick(row, TASK_FIELD_ALIASES, "due_at")),
            "remind_at": _normalize_dt(_pick(row, TASK_FIELD_ALIASES, "remind_at")),
            "category": str(_pick(row, TASK_FIELD_ALIASES, "category") or "")[:48],
        }
        for field_name in ("planned_minutes", "actual_minutes"):
            value = _as_int(_pick(row, TASK_FIELD_ALIASES, field_name))
            if value is not None:
                payload[field_name] = value

        key = str(row.get("id") or row.get("uuid") or f"{index}:{payload['title']}")
        if payload["title"] in seen:
            bucket["skipped"] += 1      # дубль строки внутри legacy-базы
            continue
        seen.add(payload["title"])

        existing = db.execute(
            select(Task).where(Task.owner_id == owner_id,
                              Task.title == payload["title"],
                              Task.deleted_at.is_(None))
        ).scalars().first()
        if _journal(db, owner_id, path, "task", key) is not None and existing is not None:
            bucket["skipped"] += 1
            continue
        if existing is not None:
            entities.update_entity(db, settings, existing, "task", payload, device_id=device_id)
            bucket["updated"] += 1
            target_id = existing.id
        else:
            target_id = entities.create_entity(db, settings, owner_id, "task", payload,
                                              device_id=device_id).id
            bucket["created"] += 1
        if _journal(db, owner_id, path, "task", key) is None:
            _note_import(db, owner_id, path, "task", key, target_id, payload)
            db.flush()


def _import_lessons(db, con, owner_id, path, settings, device_id, report, tables) -> None:
    table = _first_table(tables, LEGACY_LESSON_TABLES)
    if table is None:
        return
    bucket = report["schedule"]
    seen: set[str] = set()
    for index, row in enumerate(_read_rows(con, table)):
        subject = _pick(row, LESSON_FIELD_ALIASES, "subject")
        day = _normalize_date(_pick(row, LESSON_FIELD_ALIASES, "date"))
        if not subject or not day:
            bucket["skipped"] += 1
            continue
        start = str(_pick(row, LESSON_FIELD_ALIASES, "start_time") or "")[:5]
        payload: dict[str, Any] = {
            "group_name": str(_pick(row, LESSON_FIELD_ALIASES, "group_name") or "ИС-21")[:24],
            "date": day,
            "slot": _as_int(row.get("pair")) or 0,
            "start_time": start,
            "end_time": str(_pick(row, LESSON_FIELD_ALIASES, "end_time") or "")[:5],
            "subject": str(subject).strip()[:200],
            "teacher": str(_pick(row, LESSON_FIELD_ALIASES, "teacher") or "")[:120],
            "room": str(_pick(row, LESSON_FIELD_ALIASES, "room") or "")[:48],
            "lesson_type": str(_pick(row, LESSON_FIELD_ALIASES, "lesson_type") or "")[:48],
            "source_file": path.name,
        }
        payload["slot"] = min(payload["slot"], 12)
        identity = f"{day}:{start}:{payload['subject']}"
        if identity in seen:
            bucket["skipped"] += 1
            continue
        seen.add(identity)

        key = str(row.get("id") or identity)
        existing = db.execute(
            select(ScheduleEntry).where(ScheduleEntry.owner_id == owner_id,
                                        ScheduleEntry.date == day,
                                        ScheduleEntry.subject == payload["subject"],
                                        ScheduleEntry.start_time == start,
                                        ScheduleEntry.deleted_at.is_(None))
        ).scalars().first()
        if _journal(db, owner_id, path, "lesson", key) is not None and existing is not None:
            bucket["skipped"] += 1
            continue
        if existing is not None:
            entities.update_entity(db, settings, existing, "schedule", payload,
                                   device_id=device_id)
            bucket["updated"] += 1
            target_id = existing.id
        else:
            target_id = entities.create_entity(db, settings, owner_id, "schedule", payload,
                                              device_id=device_id).id
            bucket["created"] += 1
        if _journal(db, owner_id, path, "lesson", key) is None:
            _note_import(db, owner_id, path, "lesson", key, target_id, payload)
            db.flush()


def _match_users(db, owner_id, con, report, tables) -> None:
    """Пользователей legacy-базы только сопоставляем: второй владелец не нужен."""
    table = _first_table(tables, LEGACY_USER_TABLES)
    if table is None:
        return
    from ..models import Owner

    usernames = {str(row.get("username") or "").strip()
                 for row in _read_rows(con, table)} - {""}
    if not usernames:
        return
    matched = db.execute(
        select(Owner).where(Owner.username.in_(sorted(usernames)))
    ).scalars().all()
    report["users"]["matched"] = len(matched)
    report["users"]["created"] = 0
    if not matched:
        report["warnings"].append(
            "В legacy-базе есть пользователи, но ни один не совпал с владельцем — "
            "данные перенесены в текущего владельца, второй пользователь не создавался.")


def _import_profile(db, con, owner_id, path, settings, device_id, report, tables) -> None:
    table = _first_table(tables, LEGACY_PROFILE_TABLES)
    if table is None:
        return
    rows = _read_rows(con, table)
    if not rows:
        return
    row = rows[0]
    payload: dict[str, Any] = {}
    for field_name in PROFILE_FIELD_ALIASES:
        value = _pick(row, PROFILE_FIELD_ALIASES, field_name)
        if value in (None, ""):
            continue
        if field_name in ("course", "semester"):
            number = _as_int(value)
            if number is not None:
                payload[field_name] = number
        else:
            payload[field_name] = str(value).strip()[:160]
    if not payload:
        return
    payload["source"] = "legacy_import"
    profile = get_or_create_profile(db, owner_id)
    entities.update_entity(db, settings, profile, "student_profile", payload,
                           device_id=device_id)
    report["profile"]["updated"] += 1
    key = str(row.get("id") or "profile")
    if _journal(db, owner_id, path, "profile", key) is None:
        _note_import(db, owner_id, path, "profile", key, profile.id, payload)
        db.flush()
