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

v1.5.11 (gov): изоляция истории по сессиям + потокобезопасность.
  Раньше был один глобальный список chat_history и один путь _HISTORY_FILE:
  при параллельных запросах (Telegram, v1.7) контексты разных пользователей
  смешивались бы. Теперь у каждой сессии (чат GUI / пользователь бота) своя
  история и свой файл, запись — под замком threading.RLock. Замок держится
  только на чтении/записи истории, медленный HTTP-запрос к LM Studio идёт
  БЕЗ замка — сессии не ждут друг друга.
"""
import json
import os
import re
import threading

import requests

from config import LM_STUDIO_URL, is_gov_build
from ai.prompts import build_system_prompt
from core.memory import load_memory
from core.sanitizer import sanitize
from core.settings import load_settings
from core.user_profile import get_profile_context


# v1.5.11: потокобезопасное хранилище историй по сессиям.
#   GUI: сессия = id чата (переключается через set_chat_history_store);
#   Telegram (v1.7): сессия = telegram user id (передаётся в ask_llm напрямую).
_HISTORY_DIR = os.path.join("data", "chat_history")
_HISTORY_WINDOW = 10
_LEGACY_HISTORY_FILE = os.path.join("data", "chat_history.json")  # до v1.5.8

_history_lock = threading.RLock()
_sessions = {}
_current_session = "main"


def _safe_session_id(session_id) -> str:
    """Почистить id сессии, чтобы он был безопасным именем файла."""
    sid = re.sub(r"[^A-Za-z0-9_\-А-Яа-яЁё]", "_", str(session_id or "main"))
    sid = sid.strip("_") or "main"
    return sid[:64]


def _session_file(session_id: str) -> str:
    return os.path.join(_HISTORY_DIR, _safe_session_id(session_id) + ".json")


def _load_session_file(session_id: str) -> list:
    """Прочитать историю сессии с диска (пустой список, если файла нет)."""
    path = _session_file(session_id)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data[-_HISTORY_WINDOW:]
    except Exception:
        pass
    # Миграция древнего формата (до v1.5.8) для главной сессии
    if _safe_session_id(session_id) == "main":
        try:
            if os.path.exists(_LEGACY_HISTORY_FILE):
                with open(_LEGACY_HISTORY_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        if isinstance(data, list):
                            return data[-_HISTORY_WINDOW:]
        except Exception:
            pass
    return []


def _save_session_file(session_id: str, history: list):
    """Сохранить историю сессии на диск (атомарно: tmp-файл + replace)."""
    try:
        os.makedirs(_HISTORY_DIR, exist_ok=True)
        path = _session_file(session_id)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(history[-_HISTORY_WINDOW:], f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        pass


def _get_session(session_id) -> list:
    """Взять (или подгрузить с диска) историю сессии. Вызывать ПОД ЗАМКОМ."""
    sid = _safe_session_id(session_id or _current_session)
    hist = _sessions.get(sid)
    if hist is None:
        hist = _load_session_file(sid)
        _sessions[sid] = hist
    return hist


def set_chat_history_store(chat_id: str):
    """
    Переключить текущую сессию LLM-памяти (вызывается GUI при старте
    и при переключении чатов). Сигнатура сохранена для совместимости.
    """
    global _current_session
    sid = _safe_session_id(chat_id)
    with _history_lock:
        _current_session = sid
        _get_session(sid)


def get_current_session() -> str:
    """Id текущей сессии (для GUI и отладки)."""
    return _current_session


def clear_chat_history(session_id=None):
    """
    Очистить историю сессии (по умолчанию — текущей) в памяти и на диске,
    чтобы память не «возрождалась» после рестарта.
    """
    sid = _safe_session_id(session_id or _current_session)
    with _history_lock:
        _sessions[sid] = []
        try:
            path = _session_file(sid)
            if os.path.exists(path):
                os.remove(path)
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
    session_id=None,
) -> str:
    """
    Отправить запрос локальной LLM и вернуть ответ.

    :param user_text: текст запроса пользователя
    :param extra_context: дополнительный контекст (снимок системы и т.п.)
    :param complexity: сложность запроса — simple / normal / complex
    :param session_id: id сессии истории (чат GUI / telegram user id).
        Если не задан — используется текущая сессия
        (см. set_chat_history_store).
    """
    sid = _safe_session_id(session_id or _current_session)

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

    with _history_lock:
        session_hist = _get_session(sid)
        session_hist.append({"role": "user", "content": user_text})
        _save_session_file(sid, session_hist)
        messages += session_hist[-_HISTORY_WINDOW:]

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

        # v1.5.10: ГОВ-сборка — фильтруем ответ перед памятью и GUI
        if is_gov_build():
            answer = sanitize(answer)

        with _history_lock:
            session_hist = _get_session(sid)
            session_hist.append({"role": "assistant", "content": answer})
            del session_hist[:-_HISTORY_WINDOW]
            _save_session_file(sid, session_hist)

        return answer

    except requests.exceptions.ConnectionError:
        return "LM Studio недоступна. Запусти LM Studio и включи локальный сервер."
    except Exception as e:
        return f"Ошибка подключения к LM Studio: {e}"


# v1.5.11: история подгружается лениво, по сессиям (_get_session), —
# при импорте модуля ничего с диска не читаем.
