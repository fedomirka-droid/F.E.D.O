import json
from pathlib import Path

MEMORY_FILE = Path("data/memory.json")


def ensure_memory_file():
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not MEMORY_FILE.exists():
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)


def load_memory():
    ensure_memory_file()

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()

            if not content:
                return {}

            return json.loads(content)
    except json.JSONDecodeError:
        return {}


def save_memory(memory: dict):
    ensure_memory_file()

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=4)


def remember(key: str, value: str):
    memory = load_memory()
    memory[key] = value
    save_memory(memory)


def recall(key: str):
    memory = load_memory()
    return memory.get(key, "Я этого не помню.")


def get_all_memory():
    return load_memory()