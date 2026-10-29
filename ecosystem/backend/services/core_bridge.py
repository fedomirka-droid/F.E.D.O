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


# Команды Core с побочными действиями на ПК. Их НЕ выполняет AI Router:
# действие может быть инициировано текстом из Telegram или ответом модели.
SIDE_EFFECT_KEYWORDS = (
    "браузер", "google", "гугл", "ютуб", "youtube", "музык", "папк", "проводник",
    "открой", "запусти", "выключи", "перезагруз", "заверши", "удали", "терминал",
)


def core_local_route(text: str) -> str | None:
    """Безопасный локальный маршрут Core: команды профиля/памяти/статуса/монитора.

    Возвращает ответ или None. Команды с побочными действиями (открыть браузер,
    папку, завершить процесс) здесь запрещены — только явные кнопки Desktop.
    """
    low = (text or "").lower()
    if any(keyword in low for keyword in SIDE_EFFECT_KEYWORDS):
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
