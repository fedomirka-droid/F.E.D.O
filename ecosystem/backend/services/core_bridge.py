"""Мост к существующему F.E.D.O. Core (v1.5.x).

Ничего в Core не переписывается: берём его монитор системы, конфиг,
prompt-ы и локальный роутер. Если Core нет (например, в контейнере HUB
без репозитория), функции честно деградируют.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def core_available() -> bool:
    return (REPO_ROOT / "core" / "system_monitor.py").exists()


def core_version() -> str:
    try:
        import config as core_config  # type: ignore

        return str(getattr(core_config, "APP_VERSION", "unknown"))
    except Exception:
        return "unavailable"


def core_build() -> str:
    try:
        import config as core_config  # type: ignore

        return str(getattr(core_config, "FEDO_BUILD", "standard"))
    except Exception:
        return "unavailable"


def system_snapshot() -> dict:
    """Снимок системы из Core (CPU/RAM/диск/GPU/топ процессов)."""
    try:
        from core.system_monitor import get_system_snapshot  # type: ignore

        return get_system_snapshot(cpu_interval=0.1)
    except Exception as exc:  # pragma: no cover - зависит от окружения
        return {"error": f"Core monitor недоступен: {exc}", "platform": sys.platform}


def system_summary() -> str:
    try:
        from core.system_monitor import get_system_summary  # type: ignore

        return get_system_summary()
    except Exception as exc:  # pragma: no cover
        return f"Монитор недоступен: {exc}"


def build_system_prompt(personality_mode: str = "СССР", answer_mode: str = "normal", response_language: str = "auto") -> str:
    """Системный prompt — из Core (личности, язык, режим ответов)."""
    try:
        from ai.prompts import build_system_prompt as core_prompt  # type: ignore

        return core_prompt(
            personality_mode=personality_mode,
            answer_mode=answer_mode,
            response_language=response_language,
        )
    except Exception:
        return (
            "Ты — F.E.D.O., персональный ассистент. Отвечай по-русски, кратко и по делу. "
            "Не выполняй системные команды самостоятельно."
        )


# --------------------------------------------------------------------------- #
# Разделение «обычный чат» и «системные действия»
# --------------------------------------------------------------------------- #
# Политика — БЕЛЫЙ список. Раньше здесь был чёрный список ключевых слов, и
# команды «найди <запрос>» (открывает браузер) и «очисти лог» (удаляет файл
# лога) проходили как обычный чат: текст из Telegram/AI мог вызвать действие
# на ПК. Теперь выполняется только явно перечисленное ниже.
SAFE_EXACT_COMMANDS = frozenset({
    "статус", "/status", "время", "/time",
    "система", "состояние системы", "состояние пк", "состояние компьютера",
    "память", "вся память", "/memory", "помощь", "/help",
    "кто я", "кто тебя создал", "кто тебя создал?", "кто твой создатель",
    "кто создал тебя", "кто создал fedo", "кто создал f.e.d.o",
})

SAFE_PREFIX_COMMANDS = (
    "как меня зовут",   # чтение профиля
    "вспомни ",         # чтение памяти
    "запомни ",         # запись памяти (данные пользователя, не ПК)
    "меня зовут ",      # запись профиля
    "зови меня ",       # запись профиля
    "я ",               # запись профиля («я студент»)
    "мой город ",
    "тебя создал ",
    "покажи состояние",  # чтение монитора (без действий)
)

# Дополнительный барьер: даже если команда похожа на разрешённую, эти слова
# означают потенциальное действие на ПК или удаление данных.
DENY_KEYWORDS = (
    "открой", "открыть", "найди", "поиск", "запусти", "выключи", "перезагруз",
    "заверши", "убей", "удали", "очист", "сброс", "стирай", "терминал", "shell",
    "cmd", "powershell", "bash", "браузер", "проводник", "папк", "ютуб", "youtube",
    "google", "гугл", "музык", "путь", "лог", "установи", "скачай", "screen",
    "скриншот", "клавиатур", "мышь", "процесс",
)


def normalize_command_text(text: str) -> str:
    low = (text or "").lower().replace("ё", "е").strip().lstrip("- ").strip()
    return " ".join(low.split())


def is_safe_local_command(text: str) -> bool:
    """Можно ли выполнить текст как локальную команду Core (без побочных действий)."""
    low = normalize_command_text(text)
    if not low:
        return False
    if any(keyword in low for keyword in DENY_KEYWORDS):
        return False
    if low in SAFE_EXACT_COMMANDS:
        return True
    return any(low == prefix.strip() or low.startswith(prefix)
               for prefix in SAFE_PREFIX_COMMANDS)


def core_local_route(text: str) -> str | None:
    """Безопасный локальный маршрут Core: только чтение статуса/профиля/памяти.

    Возвращает ответ или None. Любая команда с побочным действием на ПК
    (открыть браузер/папку, удалить лог, запустить процесс) здесь не
    выполняется — такие действия возможны только явными кнопками Desktop
    через Device Manager с подтверждением владельца.
    """
    if not is_safe_local_command(text):
        return None
    try:
        from core.commands import handle_command  # type: ignore

        answer = handle_command(text)
        if answer:
            return answer
    except Exception:
        pass
    return None


def core_settings() -> dict:
    try:
        from core.settings import load_settings  # type: ignore

        data = load_settings()
        return {k: v for k, v in data.items() if "key" not in k.lower()}
    except Exception:
        return {}


def core_chats() -> list:
    try:
        from core.chat_manager import load_registry  # type: ignore

        reg = load_registry() or {}
        return reg.get("chats", [])
    except Exception:
        return []


def configure_core_paths(data_dir: str) -> None:
    """Core пишет data/ относительно cwd — переключаем на каталог приложения."""
    os.environ.setdefault("FEDO_DATA_DIR", data_dir)
