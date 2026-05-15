import requests

from config import LM_STUDIO_URL
from ai.prompts import build_system_prompt
from core.memory import load_memory
from core.settings import load_settings


chat_history = []
def clear_chat_history():
    global chat_history
    chat_history = []


def get_current_lm_url():
    settings = load_settings()
    return settings.get("lm_studio_url", LM_STUDIO_URL)


def is_lm_studio_online():
    try:
        lm_url = get_current_lm_url()
        url = lm_url.replace("/chat/completions", "/models")

        response = requests.get(url, timeout=2)
        return response.status_code == 200

    except Exception:
        return False


def get_model_name():
    try:
        lm_url = get_current_lm_url()
        url = lm_url.replace("/chat/completions", "/models")

        response = requests.get(url, timeout=2)
        data = response.json()

        return data["data"][0]["id"]

    except Exception:
        return "НЕ ОБНАРУЖЕНА"


def ask_llm(user_text: str) -> str:
    global chat_history

    settings = load_settings()

    system_prompt = build_system_prompt(
        style_mode=settings.get("style_mode", "soviet"),
        answer_mode=settings.get("answer_mode", "normal")
    )

    lm_url = settings.get("lm_studio_url", LM_STUDIO_URL)

    memory = load_memory()

    memory_context = ""
    if memory:
        memory_context = "Известные данные о пользователе:\n"
        for key, value in memory.items():
            memory_context += f"{key}: {value}\n"

    messages = [
        {"role": "system", "content": system_prompt}
    ]

    if memory_context:
        messages.append({"role": "system", "content": memory_context})

    chat_history.append({"role": "user", "content": user_text})
    messages += chat_history

    max_tokens = 250

    if settings.get("answer_mode", "normal") == "short":
        max_tokens = 120
    elif settings.get("answer_mode", "normal") == "detailed":
        max_tokens = 900

    data = {
        "model": "qwen/qwen2.5-vl-7b",
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": max_tokens
    }

    try:
        response = requests.post(lm_url, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()

        answer = result["choices"][0]["message"]["content"]

        chat_history.append({"role": "assistant", "content": answer})

        if len(chat_history) > 10:
            chat_history = chat_history[-10:]

        return answer

    except Exception as e:
        return f"Ошибка подключения к LM Studio: {e}"