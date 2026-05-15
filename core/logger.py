from datetime import datetime
from pathlib import Path

LOG_FILE = Path("logs/session.log")

def clear_log():
    LOG_FILE.parent.mkdir(exist_ok=True)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

    return "Журнал системы очищен, товарищ."

def log(message: str):
    LOG_FILE.parent.mkdir(exist_ok=True)

    time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{time}] {message}\n")

