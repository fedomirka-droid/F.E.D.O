"""
F.E.D.O Core — Chat Manager (v1.5.8)

Много-чат с папками (как в мессенджерах):

    data/
    ├── chats/
    │   ├── chats.json              (реестр чатов и папок)
    │   ├── Общий/
    │   │   └── Первый чат.txt
    │   └── Проекты/
    │       └── F.E.D.O.txt
    └── chat_history/
        └── <chat_id>.json          (LLM-память каждого чата отдельно)

Один чат = один текстовый файл. Папки — для организации.
"""
import json
import os
import re
from datetime import datetime

CHAT_DIR = os.path.join("data", "chats")
REGISTRY_FILE = os.path.join(CHAT_DIR, "chats.json")
HISTORY_DIR = os.path.join("data", "chat_history")
DEFAULT_FOLDER = "Общий"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _safe_name(name) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "", str(name or "")).strip()
    return name[:60] or "чат"


def _ensure_dirs():
    os.makedirs(CHAT_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)


def chat_text_path(chat: dict) -> str:
    return os.path.join(CHAT_DIR, _safe_name(chat.get("folder", DEFAULT_FOLDER)),
                        _safe_name(chat.get("title", "чат")) + ".txt")


def load_registry() -> dict:
    try:
        if os.path.exists(REGISTRY_FILE):
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("chats"), list):
                return data
    except Exception:
        pass
    return None


def save_registry(reg: dict):
    _ensure_dirs()
    reg["updated"] = _now()
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)


def ensure_registry() -> dict:
    """Загрузить реестр; если его нет — создать дефолтный (+ миграция)."""
    reg = load_registry()
    if reg is not None:
        return reg

    reg = {
        "folders": [DEFAULT_FOLDER],
        "chats": [],
        "active": "main",
    }

    # дефолтный чат
    reg["chats"].append({
        "id": "main",
        "title": "Первый чат",
        "folder": DEFAULT_FOLDER,
        "created": _now(),
    })

    # миграция v1.5.3: старые дневные файлы data/chats/*.txt → «Первый чат»
    try:
        _ensure_dirs()
        old_files = sorted(
            f for f in os.listdir(CHAT_DIR)
            if f.endswith(".txt") and os.path.isfile(os.path.join(CHAT_DIR, f))
        )
        if old_files:
            target = chat_text_path(reg["chats"][0])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as out:
                for name in old_files:
                    with open(os.path.join(CHAT_DIR, name), "r",
                              encoding="utf-8", errors="replace") as src:
                        out.write(src.read())
                    os.remove(os.path.join(CHAT_DIR, name))
    except Exception:
        pass

    # миграция LLM-памяти v1.5.3: data/chat_history.json → main.json
    try:
        old_hist = os.path.join("data", "chat_history.json")
        new_hist = os.path.join(HISTORY_DIR, "main.json")
        if os.path.exists(old_hist) and not os.path.exists(new_hist):
            os.makedirs(HISTORY_DIR, exist_ok=True)
            os.replace(old_hist, new_hist)
    except Exception:
        pass

    save_registry(reg)
    return reg


def list_folders(reg: dict):
    folders = list(reg.get("folders") or [DEFAULT_FOLDER])
    if DEFAULT_FOLDER not in folders:
        folders.insert(0, DEFAULT_FOLDER)
    return folders


def find_chat(reg: dict, chat_id: str) -> dict:
    for chat in reg.get("chats", []):
        if chat.get("id") == chat_id:
            return chat
    return None


def active_chat(reg: dict) -> dict:
    chat = find_chat(reg, reg.get("active", ""))
    if chat is None and reg.get("chats"):
        chat = reg["chats"][0]
    return chat


def create_chat(reg: dict, title: str, folder: str) -> dict:
    title = _safe_name(title) or f"Чат {len(reg['chats']) + 1}"
    folder = _safe_name(folder) or DEFAULT_FOLDER
    if folder not in reg["folders"]:
        reg["folders"].append(folder)

    chat = {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "title": title,
        "folder": folder,
        "created": _now(),
    }
    reg["chats"].append(chat)
    reg["active"] = chat["id"]

    # файл чата (пустой, появится с первой репликой)
    os.makedirs(os.path.dirname(chat_text_path(chat)), exist_ok=True)
    save_registry(reg)
    return chat


def delete_chat(reg: dict, chat_id: str) -> bool:
    chat = find_chat(reg, chat_id)
    if chat is None:
        return False

    try:
        path = chat_text_path(chat)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    try:
        hist = os.path.join(HISTORY_DIR, str(chat_id) + ".json")
        if os.path.exists(hist):
            os.remove(hist)
    except Exception:
        pass

    reg["chats"] = [c for c in reg["chats"] if c.get("id") != chat_id]
    if reg.get("active") == chat_id:
        reg["active"] = reg["chats"][0]["id"] if reg["chats"] else ""
    save_registry(reg)
    return True


def set_active(reg: dict, chat_id: str):
    reg["active"] = chat_id
    save_registry(reg)


def add_folder(reg: dict, name: str) -> str:
    folder = _safe_name(name) or "Папка"
    if folder not in reg["folders"]:
        reg["folders"].append(folder)
        save_registry(reg)
    return folder


def append_chat_line(chat: dict, line: str):
    """Дописать строку в файл чата (с меткой времени)."""
    try:
        path = chat_text_path(chat)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line.rstrip("\n") + "\n")
    except Exception:
        pass


def read_chat_lines(chat: dict, limit: int = 80):
    """Прочитать последние limit строк файла чата."""
    try:
        path = chat_text_path(chat)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip().splitlines()[-limit:]
    except Exception:
        return []


def chat_line_count(chat: dict) -> int:
    try:
        path = chat_text_path(chat)
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0
