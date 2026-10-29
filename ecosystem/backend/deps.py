"""Зависимости FastAPI: БД, аутентификация, права, лимиты."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .db import utcnow
from .models import Device, Owner, UserSession
from .security import RateLimiter, constant_time_eq, token_hash

bearer_scheme = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Session:
    """Сессия БД на запрос (commit/rollback — в Database.session)."""
    with request.app.state.db.session() as session:
        yield session


def get_limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbDep = Annotated[Session, Depends(get_db)]
LimiterDep = Annotated[RateLimiter, Depends(get_limiter)]


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(limiter: RateLimiter, key: str, limit: int, window: int, detail: str) -> None:
    allowed, retry = limiter.hit(key, limit, window)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry)},
        )


def _load_session(token: str, db: Session) -> UserSession | None:
    hashed = token_hash(token)
    session = db.execute(select(UserSession).where(UserSession.token_hash == hashed)).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


class AuthContext:
    """Аутентифицированный владелец + сессия."""

    def __init__(self, owner: Owner, session: UserSession | None, device: Device | None = None):
        self.owner = owner
        self.session = session
        self.device = device

    @property
    def owner_id(self) -> str:
        return self.owner.id


def require_owner(
    request: Request,
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    session = _load_session(credentials.credentials, db)
    if session is None:
        raise HTTPException(status_code=401, detail="Сессия недействительна или истекла")
    owner = db.get(Owner, session.owner_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status_code=401, detail="Владелец недоступен")
    session.last_seen_at = utcnow()
    device = db.get(Device, session.device_id) if session.device_id else None
    return AuthContext(owner, session, device)


OwnerDep = Annotated[AuthContext, Depends(require_owner)]


def require_device(
    request: Request,
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> Device:
    """Аутентификация устройства по device-токену (X-Device-Token / Bearer)."""
    token = ""
    if credentials and credentials.credentials:
        token = credentials.credentials
    token = request.headers.get("x-device-token", token)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется токен устройства")
    hashed = token_hash(token)
    device = db.execute(select(Device).where(Device.token_hash == hashed)).scalar_one_or_none()
    if device is None or device.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Устройство не авторизовано")
    device.last_seen_at = utcnow()
    return device


DeviceDep = Annotated[Device, Depends(require_device)]


def require_bot_service(request: Request, settings: SettingsDep) -> None:
    """Сервисный токен Telegram-бота (у бота нет прав владельца)."""
    expected = settings.bot_service_token
    provided = request.headers.get("x-bot-token", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Telegram-интеграция не настроена на HUB")
    if not provided or not constant_time_eq(expected, provided):
        raise HTTPException(status_code=403, detail="Сервисный токен бота неверен")


def audit(db: Session, owner_id: str, action: str, target: str = "", actor: str = "owner", **detail) -> None:
    from .models import AuditLog

    db.add(AuditLog(owner_id=owner_id, actor=actor, action=action, target=target, detail=detail))


class SyncPrincipal:
    """Кто синхронизируется: владелец (сессия) или устройство (device-токен)."""

    def __init__(self, owner_id: str, device_id: str = "", via: str = "session"):
        self.owner_id = owner_id
        self.device_id = device_id
        self.via = via


def require_sync_principal(
    request: Request,
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> SyncPrincipal:
    token = request.headers.get("x-device-token", "") or (credentials.credentials if credentials else "")
    if not token:
        raise HTTPException(status_code=401, detail="Требуется сессия или токен устройства")
    session = _load_session(token, db)
    if session is not None:
        owner = db.get(Owner, session.owner_id)
        if owner is None or not owner.is_active:
            raise HTTPException(status_code=401, detail="Владелец недоступен")
        session.last_seen_at = utcnow()
        return SyncPrincipal(session.owner_id, session.device_id or "", "session")
    device = db.execute(select(Device).where(Device.token_hash == token_hash(token))).scalar_one_or_none()
    if device is None or device.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Недействительный токен устройства")
    device.last_seen_at = utcnow()
    return SyncPrincipal(device.owner_id, device.id, "device")


SyncDep = Annotated[SyncPrincipal, Depends(require_sync_principal)]
