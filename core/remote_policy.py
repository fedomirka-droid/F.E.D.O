"""
F.E.D.O Core — Remote Policy (v1.5.11, gov)

Политика удалённого доступа для Telegram-бота (v1.7).

Три рубежа:
  1) авторизация — отвечают только владельцы из telegram_owner_ids
     (настройки или FEDO_TELEGRAM_OWNER_IDS); пустой список =
     удалёнка запрещена всем (fail closed);
  2) белый список — удалённо выполняются только безопасные команды,
     всё остальное отклоняется;
  3) подтверждение — опасные действия («открой путь», проводник, лог,
     очистка лога) требуют одноразового кода (двухшаговая схема:
     бот запросит код отдельным сообщением, см. confirm_remote).

Локальный GUI и консоль идут через source="local" и политикой
не ограничиваются.
"""
import os
import time
import uuid

from core.logger import log


# Безопасные удалённые команды (чтение/инфо + безобидные открытия)
REMOTE_SAFE = frozenset({
    "status", "time", "system", "memory", "profile",
    "recall", "remember", "help",
    "open_browser", "open_youtube", "open_music", "open_site",
})

# Опасные: только с подтверждением по коду
REMOTE_CONFIRM = frozenset({
    "open_path", "open_explorer", "project_folder", "open_log", "clear_log",
})

CONFIRM_TTL = 300  # 5 минут на ввод кода
_pending = {}  # token -> {"action", "arg", "user", "ts"}


def get_owner_ids() -> list:
    """Список id владельцев: настройки + env, уникальные, по порядку."""
    owners = []
    try:
        from core.settings import load_settings
        raw = load_settings().get("telegram_owner_ids", [])
        if isinstance(raw, (list, tuple)):
            owners += [str(o).strip() for o in raw if str(o).strip()]
    except Exception:
        pass
    env_raw = os.environ.get("FEDO_TELEGRAM_OWNER_IDS", "")
    owners += [p.strip() for p in env_raw.split(",") if p.strip()]
    seen = set()
    result = []
    for owner in owners:
        if owner not in seen:
            seen.add(owner)
            result.append(owner)
    return result


def authorize_remote(remote_user) -> bool:
    """True — пользователь в списке владельцев. Пустой список = запрет всем."""
    owners = get_owner_ids()
    if not owners:
        return False
    ok = str(remote_user).strip() in owners
    try:
        log(f"[REMOTE] auth user={remote_user} -> {'OK' if ok else 'DENY'}")
    except Exception:
        pass
    return ok


def _cleanup_pending():
    now = time.time()
    expired = [t for t, p in _pending.items() if now - p["ts"] > CONFIRM_TTL]
    for token in expired:
        del _pending[token]


def request_confirmation(command_key: str, arg: str, remote_user) -> str:
    """Создать одноразовый код подтверждения для опасного действия."""
    _cleanup_pending()
    token = uuid.uuid4().hex[:8]
    _pending[token] = {
        "action": command_key,
        "arg": arg or "",
        "user": str(remote_user),
        "ts": time.time(),
    }
    return token


def confirm_remote(token: str, remote_user=None):
    """
    Подтвердить действие кодом (вызовет бот в v1.7).
    Возвращает {"action", "arg"} или None (нет кода / протух / чужой).
    """
    _cleanup_pending()
    token = str(token or "").strip().lower()
    item = _pending.pop(token, None)
    if not item:
        return None
    if remote_user is not None and str(remote_user).strip() != item["user"]:
        return None
    return {"action": item["action"], "arg": item["arg"]}


def gate_remote(command_key: str, arg: str = "", remote_user=None):
    """
    Проверка команды для удалённого доступа.
    :return: None — выполнять; иначе текст отказа/запроса подтверждения.
    """
    if command_key in REMOTE_SAFE:
        return None
    if command_key in REMOTE_CONFIRM:
        token = request_confirmation(command_key, arg, remote_user)
        try:
            log(f"[REMOTE] confirm {command_key} user={remote_user} token={token}")
        except Exception:
            pass
        return (f"Опасное действие ({command_key}) требует подтверждения. "
                f"Код: {token} (действует 5 минут, одноразовый).")
    try:
        log(f"[REMOTE] deny {command_key} user={remote_user}")
    except Exception:
        pass
    return f"Команда недоступна удалённо: {command_key}."
