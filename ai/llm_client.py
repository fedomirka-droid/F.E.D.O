import requests

from config import LM_STUDIO_URL
from ai.prompts import get_system_prompt
from core.memory import load_memory


chat_history = []


def is_lm_studio_online():
    try:
        url = LM_STUDIO_URL.replace("/chat/completions", "/models")
        response = requests.get(url, timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def get_model_name():
    try:
        url = LM_STUDIO_URL.replace("/chat/completions", "/models")
        response = requests.get(url, timeout=2)
        data = response.json()

        return data["data"][0]["id"]
    except Exception:
        return "НЕ ОБНАРУЖЕНА"


def ask_llm(user_text: str) -> str:
    global chat_history

    memory = load_memory()

    memory_context = ""
    if memory:
        memory_context = "Известные данные о пользователе:\n"
        for key, value in memory.items():
            memory_context += f"{key}: {value}\n"

    messages = [
        {"role": "system", "content": get_system_prompt()}
    ]

    if memory_context:
        messages.append({"role": "system", "content": memory_context})

    chat_history.append({"role": "user", "content": user_text})
    messages += chat_history

    data = {
        "model": "qwen/qwen2.5-vl-7b",
        "messages": messages,
        "temperature": 0.7
    }

    try:
        response = requests.post(LM_STUDIO_URL, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()

        answer = result["choices"][0]["message"]["content"]

        chat_history.append({"role": "assistant", "content": answer})

        if len(chat_history) > 10:
            chat_history = chat_history[-10:]

        return answer

    except Exception as e:
        return f"Ошибка подключения к LM Studio: {e}"