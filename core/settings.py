import json
import os

SETTINGS_FILE = os.path.join("data", "settings.json")


DEFAULT_SETTINGS = {
    "voice_enabled": True,
    "lm_studio_url": "http://127.0.0.1:1234/v1/chat/completions",
    "style_mode": "soviet",
    "answer_mode": "normal"
}


def load_settings():
    try:
        if not os.path.exists("data"):
            os.makedirs("data")

        if not os.path.exists(SETTINGS_FILE):
            save_settings(DEFAULT_SETTINGS)
            return DEFAULT_SETTINGS.copy()

        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            settings = json.load(file)

        result = DEFAULT_SETTINGS.copy()
        result.update(settings)
        return result

    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict):
    if not os.path.exists("data"):
        os.makedirs("data")

    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=4)