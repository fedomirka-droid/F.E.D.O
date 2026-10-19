"""
F.E.D.O Core — Secrets (v1.5.11, gov)

Секреты (API-ключи) живут в переменных окружения, а не в JSON:

  FEDO_GEMINI_API_KEY=...  →  get_secret("gemini_api_key")

Фолбэк: старые ключи из data/settings.json (для совместимости с GUI,
где ключ вводится в настройках). Новым установкам — только env.
Полноценное шифрование секретов — v1.9 (hardening).

Важно: секреты НИКОГДА не пишутся в лог (см. core/logger.py).
"""
import json
import os

try:
    from core.settings import SETTINGS_FILE
except Exception:
    SETTINGS_FILE = os.path.join("data", "settings.json")

ENV_PREFIX = "FEDO_"


def get_secret(name: str, default: str = "") -> str:
    """Взять секрет: сначала окружение, потом legacy-JSON, потом default."""
    key = str(name or "").strip()
    if not key:
        return default
    env_val = os.environ.get(ENV_PREFIX + key.upper(), "").strip()
    if env_val:
        return env_val
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return str(data.get(key, default) or default)
    except Exception:
        pass
    return default


def get_gemini_api_key() -> str:
    """API-ключ Gemini (для гибрида v1.6.0)."""
    return get_secret("gemini_api_key", "")
