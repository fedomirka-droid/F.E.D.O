"""
F.E.D.O Core — User Profile (v1.4)

Структурированная память пользователя — отдельный уровень памяти,
отдельный от общей памяти (data/memory.json).

    Память F.E.D.O. (v1.4):
    │
    ├── data/user_profile.json  → профиль пользователя (этот модуль)
    │       имя, город, о пользователе, предпочтения, контекст, привычки
    │
    └── data/memory.json        → общая память (ключ = значение)

Профиль — это факты о человеке. Не свалка истории:
история диалогов и события живут в других модулях (v1.5+).
"""
import json
from datetime import datetime
from pathlib import Path

from core.logger import log

PROFILE_FILE = Path("data/user_profile.json")

DEFAULT_PROFILE = {
    "name": "",
    "address": "",       # форма обращения
    "city": "",
    "occupation": "",    # кем / что пользователь
    "creator": "",       # создатель системы (F.E.D.O.)
    "preferences": {},   # предпочтения: {ключ: значение}
    "context": {},       # текущий контекст: {ключ: значение}
    "habits": [],        # замеченные привычки
    "created_at": "",
    "updated_at": "",
}

# Ветхие ключи плоской памяти v1.3 → поля профиля (одноразовая миграция)
LEGACY_MEMORY_KEYS = {
    "имя": "name",
    "город": "city",
    "кто": "occupation",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_profile() -> dict:
    """Загрузить профиль (с джойном с дефолтами)."""
    try:
        if PROFILE_FILE.exists():
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    profile = json.loads(content)
                    merged = DEFAULT_PROFILE.copy()
                    merged.update(profile)
                    return merged
    except Exception:
        pass

    return DEFAULT_PROFILE.copy()


def save_profile(profile: dict):
    """Сохранить профиль с метками времени."""
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not profile.get("created_at"):
        profile["created_at"] = _now()
    profile["updated_at"] = _now()

    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=4)


def get_profile() -> dict:
    return load_profile()


def get_field(key: str):
    """Получить поле профиля."""
    return load_profile().get(key, "")


def set_field(key: str, value):
    """Установить поле профиля."""
    profile = load_profile()
    profile[key] = value
    save_profile(profile)


def add_context(key: str, value):
    """Добавить/обновить пункт текущего контекста."""
    profile = load_profile()
    profile.setdefault("context", {})[key] = value
    save_profile(profile)


def add_habit(habit: str):
    """Добавить привычку (без дублей)."""
    profile = load_profile()
    habits = profile.setdefault("habits", [])
    if habit and habit not in habits:
        habits.append(habit)
        save_profile(profile)


def get_user_name() -> str:
    """Имя пользователя из профиля (или пустая строка)."""
    return str(get_field("name") or "").strip()


def migrate_legacy_memory():
    """
    Одноразовая миграция данных v1.3:
    плоские ключи памяти (имя / город / кто) переносятся в структурированный профиль.

    Идемпотентна: повторный вызов ничего не ломает.
    """
    from core.memory import load_memory, save_memory

    try:
        memory = load_memory()
    except Exception:
        return

    changed = False
    profile = load_profile()

    for old_key, new_key in LEGACY_MEMORY_KEYS.items():
        if old_key in memory:
            old_value = str(memory[old_key]).strip()
            if old_value and not profile.get(new_key):
                profile[new_key] = old_value
            del memory[old_key]
            changed = True

    if changed:
        save_profile(profile)
        save_memory(memory)
        log("[PROFILE] Данные v1.3 из плоской памяти перенесены в профиль пользователя.")


def get_profile_context() -> str:
    """
    Текстовый контекст профиля для LLM.
    Пустая строка — если профиль ещё пуст.
    """
    profile = load_profile()

    has_core = any(profile.get(k) for k in ("name", "city", "occupation", "creator"))
    has_prefs = bool(profile.get("preferences"))
    has_context = bool(profile.get("context"))

    if not (has_core or has_prefs or has_context):
        return ""

    lines = ["Профиль пользователя:"]

    if profile.get("creator"):
        lines.append(f"Система F.E.D.O. создана пользователем: {profile['creator']}")
    if profile.get("name"):
        lines.append(f"Имя: {profile['name']}")
    if profile.get("city"):
        lines.append(f"Город: {profile['city']}")
    if profile.get("occupation"):
        lines.append(f"О пользователе: {profile['occupation']}")

    prefs = profile.get("preferences") or {}
    if prefs:
        lines.append("Предпочтения: " + "; ".join(f"{k} — {v}" for k, v in prefs.items()))

    ctx = profile.get("context") or {}
    if ctx:
        lines.append("Контекст: " + "; ".join(f"{k} — {v}" for k, v in ctx.items()))

    return "\n".join(lines)
