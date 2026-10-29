"""Безопасность: пароли, токены, шифрование секретов, подпись канала, rate limit."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
_KEY_LEN = 32


# --------------------------------------------------------------------------- #
# Пароли
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """scrypt-хэш с солью: scrypt$n$r$p$salt$hash (без сторонних зависимостей)."""
    if not password or len(password) < 8:
        raise ValueError("Пароль должен быть не короче 8 символов")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=_KEY_LEN)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Токены
# --------------------------------------------------------------------------- #
def new_token(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих символов


def new_link_code(length: int = 8) -> str:
    return "".join(secrets.choice(LINK_CODE_ALPHABET) for _ in range(length))


# --------------------------------------------------------------------------- #
# Шифрование секретов (API-ключи, channel secret)
# --------------------------------------------------------------------------- #
class SecretBox:
    """Fernet с ключом, производным от secret_key приложения."""

    def __init__(self, secret_key: str):
        digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, Exception):
            return ""


# --------------------------------------------------------------------------- #
# Подпись канала устройство↔HUB
# --------------------------------------------------------------------------- #
def sign_payload(secret: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(secret: str, payload: dict[str, Any], signature: str) -> bool:
    if not secret or not signature:
        return False
    return hmac.compare_digest(sign_payload(secret, payload), signature)


# --------------------------------------------------------------------------- #
# Rate limit (in-process, достаточен для Personal Edition на одном процессе)
# --------------------------------------------------------------------------- #
class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Вернуть (разрешено, сколько секунд ждать)."""
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            retry = int(window - (now - bucket[0])) + 1
            return False, max(retry, 1)
        bucket.append(now)
        return True, 0

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


# --------------------------------------------------------------------------- #
# Редактирование секретов в логах
# --------------------------------------------------------------------------- #
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)(authorization\"?\s*[:=]\s*\"?)(bearer\s+)?([A-Za-z0-9_\-\.]{8,})"),
    re.compile(r"(?i)(token\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-]{8,})"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
)


def redact(text: str) -> str:
    """Маскирование ключей/токенов перед записью в лог."""
    if not text:
        return ""
    out = str(text)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            out = pattern.sub(lambda m: m.group(1) + "***", out)
        else:
            out = pattern.sub("***", out)
    return out
