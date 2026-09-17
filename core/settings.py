import json
import os

SETTINGS_FILE = os.path.join("data", "settings.json")

# v1.4 — расширенные настройки
DEFAULT_SETTINGS = {
    # AI
    "ai_provider": "Hybrid (Auto)",
    "lm_studio_url": "http://127.0.0.1:1234/v1/chat/completions",
    "gemini_api_key": "",

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
            return DEFAULT_SETTINGS.copy()

        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)

        if not isinstance(saved, dict):
            return DEFAULT_SETTINGS.copy()

        result = DEFAULT_SETTINGS.copy()
        result.update(saved)
        return result

    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict):
    if not os.path.exists("data"):
        os.makedirs("data")

    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=4)
