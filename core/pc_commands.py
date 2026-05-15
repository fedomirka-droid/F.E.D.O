import os
import webbrowser
from pathlib import Path
import subprocess
import psutil
from pathlib import Path
import os

LOG_PATH = Path("logs/session.log")
PROJECT_PATH = Path.cwd()
YANDEX_MUSIC_PATH = None
def open_music():
    return "Модуль музыки не настроен. Укажите путь к приложению в локальном config-файле."

def open_log():
    try:
        os.startfile(LOG_PATH)
        return "Открываю журнал системы, товарищ."
    except Exception as e:
        return f"Ошибка открытия лога: {e}"

def is_process_running(process_name: str):
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] and process_name.lower() in proc.info["name"].lower():
            return True
    return False

def open_yandex_music():
    try:
        if is_process_running("Яндекс Музыка"):
            return "Яндекс Музыка уже активна, товарищ."

        subprocess.Popen(
            [YANDEX_MUSIC_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return "Выполняю. Запуск Яндекс Музыки, товарищ."

    except Exception as e:
        return f"Ошибка запуска Яндекс Музыки: {e}"


def open_browser():
    webbrowser.open("https://www.google.com")
    return "Открываю браузер."


def open_youtube():
    webbrowser.open("https://www.youtube.com")
    return "Открываю YouTube."


def open_project_folder():
    os.startfile(PROJECT_PATH)
    return "Открываю папку проекта."


def open_explorer():
    os.startfile("C:\\")
    return "Открываю проводник."

def open_site(query: str):
    url = f"https://www.google.com/search?q={query}"
    webbrowser.open(url)
    return f"Ищу в интернете: {query}"

def open_path(path: str):
    try:
        os.startfile(path)
        return f"Открываю: {path}"
    except:
        return "Не удалось открыть путь."