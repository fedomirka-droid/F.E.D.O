import json
import os

SETTINGS_FILE = os.path.join("data", "settings.json")

# v1.4 — расширенные настройки
DEFAULT_SETTINGS = {
    # AI
    "ai_provider": "Hybrid (Auto)",
    "lm_studio_url": "http://127.0.0.1:1234/v1/chat/completions",
    # v1.5.11: ключ в JSON — legacy. Правильное место — переменная
    # окружения FEDO_GEMINI_API_KEY (см. core/secrets.py): она важнее.
    "gemini_api_key": "",

    # v1.5.11: владельцы Telegram-бота (v1.7) — список id (числа/строки).
    # Пустой список = удалёнка запрещена всем. Запасной путь —
    # FEDO_TELEGRAM_OWNER_IDS (через запятую).
    "telegram_owner_ids": [],

    # Личность
    "personality_mode": "СССР",
    "answer_mode": "normal",
    # v1.4.2: язык ответов — auto (зеркалить язык пользователя, дефолт) / ru / en / zh
    "response_language": "auto",

    # v1.4: определение сложности запроса (по количеству слов)
    "complexity_simple_max": 5,
    "complexity_normal_max": 15,

    # v1.4: системный мониторинг
    "system_monitor_enabled": True,
    "monitor_interval": 2.0,

    # Голос
    "voice_enabled": True,
    "microphone_enabled": False,
    # v4-голоса: aidar (глубокий мужской), eugene (мужской),
    # baya, kseniya, xenia (женские), random
    "tts_speaker": "aidar",
    # v1.4.5: английский голос Silero v3_en (en_0..en_117)
    "tts_speaker_en": "en_10",

    # Интерфейс
    "developer_mode": False,
}


def load_settings():
    """Загрузить настройки. Недостающие ключи дозаполняются дефолтами (v1.4)."""
    try:
        if not os.path.exists("data"):
            os.makedirs("data")

        if not os.path.exists(SETTINGS_FILE):
            save_settings(DEFAULT_SETTINGS)
            saved = {}
        else:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
                saved = json.load(file)

        if not isinstance(saved, dict):
            saved = {}

        result = DEFAULT_SETTINGS.copy()
        result.update(saved)
    except Exception:
        result = DEFAULT_SETTINGS.copy()

    # v1.5.11: секрет из окружения важнее JSON (см. core/secrets.py).
    # os.environ читаем напрямую, чтобы не делать круговой импорт.
    env_key = os.environ.get("FEDO_GEMINI_API_KEY", "").strip()
    if env_key:
        result["gemini_api_key"] = env_key

    return result


def save_settings(settings: dict):
    if not os.path.exists("data"):
        os.makedirs("data")

    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=4)
