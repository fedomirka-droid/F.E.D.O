"""
F.E.D.O Core — LM Studio Client (v1.4)

Работа с локальной LLM через OpenAI-совместимый API LM Studio.

v1.4:
  - имя модели НЕ захардкожено: определяется автоматически через /v1/models;
  - контекст: профиль пользователя + общая память + внешний контекст
    (например, снимок состояния системы от AI Router);
  - сложность запроса (simple/normal/complex) влияет на max_tokens;
  - исправлен баг v1.3: системный prompt строился с неверным аргументом,
    из-за чего каждый запрос падал с TypeError.
"""
import json
import os

import requests

from config import LM_STUDIO_URL
from ai.prompts import build_system_prompt
from core.memory import load_memory
from core.settings import load_settings
from core.user_profile import get_profile_context


chat_history = []

# v1.5.3: память между запусками — последние 10 сообщений живут на диске
# (как на серверах: история не теряется при рестарте)
# v1.5.8: память У КАЖДОГО ЧАТА своя: data/chat_history/<chat_id>.json
_HISTORY_FILE = os.path.join("data", "chat_history.json")  # legacy (до v1.5.8)


def set_chat_history_store(chat_id: str):
    """
    v1.5.8: переключить хранилище LLM-памяти на чат chat_id
    (вызывается GUI при старте и при переключении чатов).
    """
    global _HISTORY_FILE
    target = os.path.join("data", "chat_history", str(chat_id or "main") + ".json")
    if target == _HISTORY_FILE:
        return

    _HISTORY_FILE = target
    _load_chat_history()


def _load_chat_history():
    """v1.5.3: загрузить сохранённую историю (вызывается при старте)."""
    global chat_history
    chat_history = []
    try:
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        chat_history = data[-10:]
    except Exception:
        pass


def _save_chat_history():
    """v1.5.3: сохранить историю на диск."""
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_history[-10:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def clear_chat_history():
    global chat_history
    chat_history = []
    # v1.5.3: чистим и файл, чтобы память не "возрождалась"
    try:
        if os.path.exists(_HISTORY_FILE):
            os.remove(_HISTORY_FILE)
    except Exception:
        pass


def get_current_lm_url() -> str:
    settings = load_settings()
    return settings.get("lm_studio_url", LM_STUDIO_URL)


def _normalize_base_url(url: str) -> str:
    """
    Приводит адрес из настроек к базовому (без API-пути).
    Принимает любые варианты, которые может ввести пользователь:
        http://127.0.0.1:1234
        http://127.0.0.1:1234/
        http://127.0.0.1:1234/v1
        http://127.0.0.1:1234/v1/chat/completions
    """
    u = (url or "").strip().rstrip("/")
    for suffix in (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/models",
        "/models",
        "/v1",
    ):
        if u.lower().endswith(suffix):
            u = u[: -len(suffix)]
            break
    return u


def get_models_url() -> str:
    return _normalize_base_url(get_current_lm_url()) + "/v1/models"


def get_chat_completions_url() -> str:
    return _normalize_base_url(get_current_lm_url()) + "/v1/chat/completions"


def is_lm_studio_online() -> bool:
    """Жив ли локальный сервер LM Studio (проверка по /v1/models)."""
    try:
        response = requests.get(get_models_url(), timeout=2)
        if response.status_code != 200:
            return False
        data = response.json()
        # LM Studio возвращает 200 "anyway" даже на незнакомые эндпоинты,
        # поэтому проверяем структуру ответа
        return isinstance(data, dict) and "data" in data
    except Exception:
        return False


def get_model_name() -> str:
    """
    Автоматически определить имя модели, загруженной в LM Studio.
    LM Studio принимает любое значение в поле "model",
    но корректный id делает запрос чистым и предсказуемым.
    """
    try:
        response = requests.get(get_models_url(), timeout=2)
        data = response.json()
        models = data.get("data", [])
        if models:
            return models[0].get("id", "local-model")
        return "NO MODEL LOADED"
    except Exception:
        return "OFFLINE"


# v1.4: сложность запроса → max_tokens (для answer_mode = "normal")
COMPLEXITY_TOKENS = {
    "simple": 200,
    "normal": 400,
    "complex": 900,
}


def _get_max_tokens(answer_mode: str, complexity: str | None) -> int:
    if answer_mode == "short":
        return 120
    if answer_mode == "detailed":
        return 900
    return COMPLEXITY_TOKENS.get(complexity or "normal", 400)


def ask_llm(
    user_text: str,
    extra_context: str | None = None,
    complexity: str | None = None,
) -> str:
    """
    Отправить запрос локальной LLM и вернуть ответ.

    :param user_text: текст запроса пользователя
    :param extra_context: дополнительный контекст (снимок системы и т.п.)
    :param complexity: сложность запроса — simple / normal / complex
    """
    global chat_history

    settings = load_settings()

    system_prompt = build_system_prompt(
        personality_mode=settings.get("personality_mode", "СССР"),
        answer_mode=settings.get("answer_mode", "normal"),
        response_language=settings.get("response_language", "auto"),
    )

    messages = [{"role": "system", "content": system_prompt}]

    # Контекст v1.4: профиль пользователя → общая память → внешний контекст
    context_parts = []

    profile_context = get_profile_context()
    if profile_context:
        context_parts.append(profile_context)

    memory = load_memory()
    if memory:
        lines = ["Известные данные (память F.E.D.O):"]
        for key, value in memory.items():
            lines.append(f"{key}: {value}")
        context_parts.append("\n".join(lines))

    if extra_context:
        context_parts.append(str(extra_context).strip())

    if context_parts:
        messages.append({"role": "system", "content": "\n\n".join(context_parts)})

    chat_history.append({"role": "user", "content": user_text})
    _save_chat_history()
    messages += chat_history[-10:]

    model_name = get_model_name()

    if model_name == "NO MODEL LOADED":
        return "LM Studio запущена, но модель не загружена. Загрузи модель в LM Studio."
    if model_name == "OFFLINE":
        return "LM Studio недоступна. Запусти LM Studio и включи локальный сервер."

    # v1.5.5: Агрессивному режиму нужна более высокая температура —
    # иначе модель цепляется за вежливые шаблонные фразы
    temperature = 0.9 if settings.get("personality_mode", "СССР") == "Агрессивный" else 0.6

    data = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": _get_max_tokens(settings.get("answer_mode", "normal"), complexity),
    }

    try:
        # timeout: (connect, read) — 5 сек на подключение (быстро ловим
        # "сервер не запущен"), 120 сек на генерацию (медленные локальные модели)
        response = requests.post(get_chat_completions_url(), json=data, timeout=(5, 120))
        response.raise_for_status()
        result = response.json()

        answer = result["choices"][0]["message"]["content"]

        chat_history.append({"role": "assistant", "content": answer})
        if len(chat_history) > 10:
            chat_history = chat_history[-10:]
        _save_chat_history()

        return answer

    except requests.exceptions.ConnectionError:
        return "LM Studio недоступна. Запусти LM Studio и включи локальный сервер."
    except Exception as e:
        return f"Ошибка подключения к LM Studio: {e}"


# v1.5.3: подхватываем историю при импорте модуля (один раз при старте)
_load_chat_history()
