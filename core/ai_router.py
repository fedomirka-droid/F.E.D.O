"""
F.E.D.O Core — AI Router (v1.4, базовый)

Единая точка входа в обработку запроса пользователя.
Через роутер проходят и GUI, и консоль — логика отделена от интерфейса.

Конвейер (v1.4 — простой и детерминированный):

    запрос пользователя
         ↓
    1) локальная команда (core/commands.py)
         ↓ не распознана
    2) системный запрос? → снимок состояния (core/system_monitor.py)
         ↓
    3) локальная LLM через LM Studio (ai/llm_client.py)
       — с профилем пользователя, памятью, сложностью запроса

Сложность запроса: по количеству слов (core/complexity.py).
Если LM Studio офлайн, системный запрос отвечает монитор напрямую,
без нейросети — F.E.D.O продолжает работать локально.

v1.5+: умный роутинг (семантика, Action Validator, события).
"""
import re

from ai.llm_client import ask_llm, is_lm_studio_online
from core.commands import handle_command, with_name
from core.complexity import classify
from core.logger import log
from core.system_monitor import get_system_snapshot, get_system_summary
from core.user_profile import migrate_legacy_memory

_migration_done = False

# Паттерны системных запросов (v1.4 — простая ключевая база, расширяется в v1.5)
SYSTEM_QUERY_PATTERNS = (
    r"состояние",
    r"система",
    r"компьютер",
    r"процессор",
    r"\bcpu\b",
    r"\bram\b",
    r"оперативн",
    r"\bgpu\b",
    r"видеокарт",
    r"температур",
    r"загрузк",
    r"тормозит",
    r"\bлаг\w*",
    r"мониторинг",
    r"сколько места",
    r"сколько (?:свободно|занимает) (?:памяти|места|ram)",
    r"свободн\w* (?:память|ram|место)",
    r"диск\w* (?:заполнен|свободен|занят)",
    r"топ процессов",
    r"какие процессы",
)

_SYSTEM_QUERY_RE = re.compile("|".join(f"({p})" for p in SYSTEM_QUERY_PATTERNS), re.IGNORECASE)


def _ensure_migration():
    """Одноразовая миграция данных v1.3 в профиль пользователя."""
    global _migration_done
    if _migration_done:
        return
    _migration_done = True
    try:
        migrate_legacy_memory()
    except Exception as e:
        log(f"[PROFILE] Ошибка миграции: {e}")


def is_system_query(text: str) -> bool:
    """Является ли запрос вопросом о состоянии компьютера."""
    normalized = (text or "").lower().replace("ё", "е")
    return bool(_SYSTEM_QUERY_RE.search(normalized))


def route(user_text: str) -> str:
    """
    Главная функция роутера: обработать запрос пользователя и вернуть ответ.

    :param user_text: текст запроса
    :return: ответ для пользователя (строка)
    """
    _ensure_migration()

    text = (user_text or "").strip()
    if not text:
        return ""

    complexity = classify(text)

    # 1) Локальные команды
    try:
        command_answer = handle_command(text)
    except Exception as e:
        command_answer = None
        log(f"[ROUTER] Ошибка команд: {e}")

    if command_answer:
        log(f"[ROUTER] → команда | {text[:80]}")
        return command_answer

    # 2) Системный запрос → System module
    if is_system_query(text):
        try:
            snapshot = get_system_snapshot()
            summary = get_system_summary(snapshot)

            if is_lm_studio_online():
                log(f"[ROUTER] → system + LLM | сложность: {complexity['level']}")
                return ask_llm(text, extra_context=summary, complexity=complexity["level"])

            log("[ROUTER] → system | LM Studio офлайн, прямой ответ монитора")
            return with_name(summary)
        except Exception as e:
            log(f"[ROUTER] Ошибка системного модуля: {e}")

    # 3) Локальная LLM
    log(f"[ROUTER] → LLM | сложность: {complexity['level']} ({complexity['words']} слов)")
    return ask_llm(text, complexity=complexity["level"])
