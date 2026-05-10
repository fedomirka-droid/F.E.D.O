from datetime import datetime

from ai.llm_client import chat_history
from core.logger import clear_log
from core.memory import remember, recall, get_all_memory
from core.pc_commands import (
    open_browser,
    open_youtube,
    open_project_folder,
    open_explorer,
    open_site,
    open_path,
    open_yandex_music,
    open_log,
)


def with_name(text: str):
    name = recall("имя")

    if name == "Я этого не помню.":
        return text

    return f"{name}, товарищ. {text}"


def handle_command(user_text: str):
    text = user_text.lower().strip().lstrip("- ").strip()
    text = text.replace("ё", "е")

    # Логи
    if text in ["очистка лога", "очисти лог", "очисти лога", "очистить лог"]:
        return with_name(clear_log())

    if text in ["покажи лог", "открой лог", "лог"]:
        return with_name(open_log())

    # Память: кто пользователь
    if text.startswith("как меня зовут") or text == "кто я":
        name = recall("имя")
        who = recall("кто")

        if text == "кто я":
            return with_name(f"Вы: {who}.")

        return with_name(f"Ваше имя: {name}.")

    if text.startswith("меня зовут "):
        name = text.replace("меня зовут", "", 1).strip().capitalize()

        if not name:
            return "Недостаточно данных для сохранения имени, товарищ."

        remember("имя", name)
        return f"Данные сохранены: имя = {name}, товарищ."

    if text.startswith("я "):
        info = text.replace("я", "", 1).strip().capitalize()

        if not info:
            return "Недостаточно данных для сохранения, товарищ."

        remember("кто", info)
        return with_name(f"Данные сохранены: вы — {info}.")

    if text.startswith("мой город "):
        city = text.replace("мой город", "", 1).strip().capitalize()
        remember("город", city)
        return with_name(f"Данные сохранены: город = {city}.")

    # Умные команды ПК
    if "браузер" in text or "google" in text or "гугл" in text:
        return with_name(open_browser())

    if "ютуб" in text or "youtube" in text:
        return with_name(open_youtube())

    if "музык" in text or "яндекс музыка" in text:
        return with_name(open_yandex_music())

    if "папк" in text and "проект" in text:
        return with_name(open_project_folder())

    if "проводник" in text:
        return with_name(open_explorer())

    # Базовые команды
    if text in ["статус", "/status"]:
        return with_name("Система функционирует. Статус: активен.")

    if text in ["время", "/time"]:
        now = datetime.now().strftime("%H:%M:%S")
        return with_name(f"Текущее время: {now}.")

    if text in ["очистить", "сброс", "/clear"]:
        chat_history.clear()
        return with_name("Контекст очищен.")

    if text.startswith("найди"):
        query = text.replace("найди", "", 1).strip()

        if not query:
            return with_name("Недостаточно данных для поиска.")

        return with_name(open_site(query))

    if text.startswith("открой путь"):
        path = text.replace("открой путь", "", 1).strip()

        if not path:
            return with_name("Недостаточно данных для открытия пути.")

        return with_name(open_path(path))

    # Память
    if text in ["память", "вся память", "/memory"]:
        memory = get_all_memory()

        if not memory:
            return with_name("Память пока пустая.")

        result = "Память F.E.D.O:\n"
        for key, value in memory.items():
            result += f"- {key}: {value}\n"

        return result

    if text.startswith("запомни"):
        data = text.replace("запомни", "", 1).strip()

        if "=" not in data:
            return with_name("Используй: запомни имя = Федя.")

        key, value = data.split("=", 1)
        remember(key.strip(), value.strip())
        return with_name(f"Запомнил: {key.strip()}.")

    if text.startswith("вспомни"):
        key = text.replace("вспомни", "", 1).strip()

        if not key:
            return with_name("Используй: вспомни имя.")

        return with_name(recall(key))

    if text in ["помощь", "/help"]:
        return """
Команды F.E.D.O:
- статус
- время
- помощь
- выход
- память
- запомни ключ = значение
- вспомни ключ
- найди запрос
- открой браузер
- открой ютуб
- открой папку проекта
- открой проводник
- включи музыку
- покажи лог
- очисти лог
"""

    return None