"""
F.E.D.O Core — PC Commands (v1.4, кроссплатформенно)

Linux-first: команды работают и на Linux, и на Windows.
Linux: xdg-open, домашняя папка, bash-совместимые запуски.
Windows: os.startfile, системный диск, CREATE_NO_WINDOW.
"""
import os
import platform
import shutil
import subprocess
import webbrowser

import psutil

IS_WINDOWS = os.name == "nt"

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "session.log")
PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YANDEX_MUSIC_PATH = None  # задаётся локально, если нужно


def _spawn(cmd: list):
    """Запустить процесс без окон (на Linux — просто в фоне)."""
    kwargs = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    subprocess.Popen(cmd, **kwargs)


def open_in_explorer(path: str) -> str:
    """Кроссплатформенно открыть файл или папку системным проводником."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            opener = shutil.which("xdg-open") or "xdg-open"
            _spawn([opener, path])
        return f"Открываю: {path}"
    except Exception as e:
        return f"Не удалось открыть {path}: {e}"


def open_log():
    """Открыть журнал сессии системным просмотрщиком."""
    try:
        if not os.path.exists(LOG_PATH):
            return "Журнал пока пуст, товарищ."
        return open_in_explorer(LOG_PATH)
    except Exception as e:
        return f"Ошибка открытия лога: {e}"


def is_process_running(process_name: str) -> bool:
    for proc in psutil.process_iter(["name"]):
        name = proc.info["name"]
        if name and process_name.lower() in name.lower():
            return True
    return False


def open_yandex_music():
    if not YANDEX_MUSIC_PATH:
        return "Модуль музыки не настроен. Укажите путь к приложению в локальном config."
    try:
        if is_process_running("Яндекс Музыка"):
            return "Яндекс Музыка уже активна, товарищ."

        _spawn([YANDEX_MUSIC_PATH])
        return "Выполняю. Запуск Яндекс Музыки, товарищ."
    except Exception as e:
        return f"Ошибка запуска Яндекс Музыки: {e}"


def open_music():
    return "Модуль музыки не настроен. Укажите путь к приложению в локальном config-файле."


def open_browser():
    webbrowser.open("https://www.google.com")
    return "Открываю браузер."


def open_youtube():
    webbrowser.open("https://www.youtube.com")
    return "Открываю YouTube."


def open_project_folder():
    return open_in_explorer(PROJECT_PATH)


def open_explorer():
    """Открыть домашнюю папку (кроссплатформенно)."""
    return open_in_explorer(os.path.expanduser("~"))


def open_site(query: str):
    from urllib.parse import quote
    url = f"https://www.google.com/search?q={quote(query)}"
    webbrowser.open(url)
    return f"Ищу в интернете: {query}"


def open_path(path: str):
    path = path.strip()
    if not path:
        return "Недостаточно данных для открытия пути."
    return open_in_explorer(path)
