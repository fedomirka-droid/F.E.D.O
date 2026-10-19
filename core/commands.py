"""
F.E.D.O Core — Commands (v1.4)

Локальные команды F.E.D.O.
Личные данные (имя / город / о пользователе) теперь хранятся
в структурированном профиле пользователя (core/user_profile.py),
а не в плоской памяти.

v1.5.11 (gov): команды знают источник вызова (source) — "local"
(GUI/консоль, без ограничений) или "remote" (Telegram, v1.7).
Удалённые вызовы идут через политику core/remote_policy.py:
авторизация + белый список + подтверждение опасных действий.
"""
from datetime import datetime

from ai.llm_client import clear_chat_history
from core.logger import clear_log
from core.memory import remember, recall, get_all_memory
from core.user_profile import get_field, set_field, get_user_name
from core.system_monitor import get_system_snapshot, get_system_summary
from core.remote_policy import authorize_remote, gate_remote
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


def with_name(text: str) -> str:
    """Прикрепить имя пользователя к ответу (если оно известно)."""
    name = get_user_name()
    if not name:
        return text
    return f"{name}, товарищ. {text}"


def handle_command(user_text: str, source: str = "local", remote_user=None):
    """
    Обработать локальную команду.

    :param user_text: текст пользователя
    :param source: "local" (GUI/консоль) или "remote" (Telegram, v1.7)
    :param remote_user: id удалённого пользователя (для авторизации)
    """
    # v1.5.11: чужим удалённым пользователям — сразу отказ, без разбора команд
    if source == "remote" and not authorize_remote(remote_user):
        return ("Удалённый доступ запрещён: тебя нет в списке владельцев. "
                "Попроси владельца добавить твой id в telegram_owner_ids.")

    def remote_gate(command_key: str, arg: str = ""):
        """Проверка удалённой политики: None — выполнять, иначе вернуть текст."""
        if source != "remote":
            return None
        return gate_remote(command_key, arg, remote_user)

    text = user_text.lower().strip().lstrip("- ").strip()
    text = text.replace("ё", "е")
    # v1.4.2: схлопываем лишние пробелы, чтобы команды не сбились
    # на "кто  тебя  создал" (двойные пробелы, табы, переводы строк)
    text = " ".join(text.split())

    # Логи
    if text in ["очистка лога", "очисти лог", "очисти лога", "очистить лог"]:
        denied = remote_gate("clear_log")
        if denied:
            return with_name(denied)
        return with_name(clear_log())

    if text in ["покажи лог", "открой лог", "лог"]:
        denied = remote_gate("open_log")
        if denied:
            return with_name(denied)
        return with_name(open_log())

    # Профиль пользователя
    if text.startswith("как меня зовут") or text == "кто я":
        name = get_field("name")
        who = get_field("occupation")

        if text == "кто я":
            return with_name(f"Вы: {who or '—'}.")

        return with_name(f"Ваше имя: {name or '—'}.")

    if text.startswith("меня зовут "):
        name = text.replace("меня зовут", "", 1).strip().capitalize()

        if not name:
            return "Недостаточно данных для сохранения имени, товарищ."

        set_field("name", name)
        return f"Данные сохранены: имя = {name}, товарищ."

    # v1.5.4: алиас смены имени
    if text.startswith("зови меня "):
        name = text.replace("зови меня", "", 1).strip().capitalize()

        if not name:
            return "Недостаточно данных для сохранения имени, товарищ."

        set_field("name", name)
        return f"Принято. Теперь буду обращаться к тебе как «{name}»."

    if text.startswith("я "):
        info = text.replace("я", "", 1).strip().capitalize()

        if not info:
            return "Недостаточно данных для сохранения, товарищ."

        set_field("occupation", info)
        return with_name(f"Данные сохранены: вы — {info}.")

    if text.startswith("мой город "):
        city = text.replace("мой город", "", 1).strip().capitalize()

        if not city:
            return "Недостаточно данных для сохранения города, товарищ."

        set_field("city", city)
        return with_name(f"Данные сохранены: город = {city}.")

    # Создатель системы
    if text.startswith("тебя создал "):
        creator = text.replace("тебя создал", "", 1).strip().capitalize()

        if not creator:
            return "Недостаточно данных для сохранения, товарищ."

        set_field("creator", creator)
        return f"Данные сохранены: создатель = {creator}, товарищ."

    if text in [
        "кто тебя создал", "кто тебя создал?", "кто твой создатель",
        "кто создал тебя", "кто создал fedo", "кто создал f.e.d.o",
    ]:
        creator = get_field("creator")
        if not creator:
            return with_name("Данные о создателе пока не введены. Скажи: тебя создал ...")
        return with_name(f"Эту систему создал: {creator}.")

    # Системный мониторинг (прямой ответ, без LLM)
    if text in ["система", "состояние системы", "состояние пк", "состояние компьютера"]:
        try:
            return with_name(get_system_summary(get_system_snapshot()))
        except Exception as e:
            return f"Ошибка чтения состояния системы: {e}"

    # Умные команды ПК
    if "браузер" in text or "google" in text or "гугл" in text:
        denied = remote_gate("open_browser")
        if denied:
            return with_name(denied)
        return with_name(open_browser())

    if "ютуб" in text or "youtube" in text:
        denied = remote_gate("open_youtube")
        if denied:
            return with_name(denied)
        return with_name(open_youtube())

    if "музык" in text or "яндекс музыка" in text:
        denied = remote_gate("open_music")
        if denied:
            return with_name(denied)
        return with_name(open_yandex_music())

    if "папк" in text and "проект" in text:
        denied = remote_gate("project_folder")
        if denied:
            return with_name(denied)
        return with_name(open_project_folder())

    if "проводник" in text:
        denied = remote_gate("open_explorer")
        if denied:
            return with_name(denied)
        return with_name(open_explorer())

    # Базовые команды
    if text in ["статус", "/status"]:
        return with_name("Система функционирует. Статус: активен.")

    if text in ["время", "/time"]:
        now = datetime.now().strftime("%H:%M:%S")
        return with_name(f"Текущее время: {now}.")

    if text in ["очистить", "сброс", "/clear"]:
        clear_chat_history()
        return with_name("Контекст очищен.")

    if text.startswith("найди"):
        query = text.replace("найди", "", 1).strip()

        if not query:
            return with_name("Недостаточно данных для поиска.")

        denied = remote_gate("open_site", query)
        if denied:
            return with_name(denied)
        return with_name(open_site(query))

    if text.startswith("открой путь"):
        path = text.replace("открой путь", "", 1).strip()
        denied = remote_gate("open_path", path)
        if denied:
            return with_name(denied)
        return with_name(open_path(path))

    # Память (общая)
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
- система
- помощь
- выход
- память
- меня зовут имя / зови меня имя
- как меня зовут
- тебя создал имя
- кто тебя создал
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

Спросить о состоянии компьютера можно обычным вопросом:
"Покажи состояние системы", "Почему компьютер тормозит?"

Удалённо (Telegram, с v1.7): работают безопасные команды для владельца,
опасные действия — только с подтверждением по коду.
"""

    return None
