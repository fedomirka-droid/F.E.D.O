"""Владелец: первичная настройка, вход, сессии, смена пароля."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import utcnow
from ..deps import DbDep, LimiterDep, OwnerDep, SettingsDep, audit, client_ip, enforce_rate_limit
from ..models import Owner, UserSession
from ..security import constant_time_eq, hash_password, new_token, token_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    device_name: str = Field(default="", max_length=80)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


def _owner_count(db) -> int:
    return len(db.execute(select(Owner.id)).scalars().all())


@router.get("/status")
def status(db: DbDep, settings: SettingsDep) -> dict:
    return {
        "owner_exists": _owner_count(db) > 0,
        "public_registration": settings.allow_public_registration,
        "needs_setup": _owner_count(db) == 0,
        "role": settings.role,
        "edition": settings.edition,
        "setup_token_required": bool(settings.setup_token),
    }


@router.post("/setup")
def setup(payload: SetupRequest, request: Request, db: DbDep, settings: SettingsDep, limiter: LimiterDep) -> dict:
    enforce_rate_limit(limiter, f"setup:{client_ip(request)}", 5, 300, "Слишком много попыток настройки")
    if _owner_count(db) > 0:
        raise HTTPException(status_code=409, detail="Владелец уже создан")
    if settings.setup_token:
        provided = request.headers.get("x-setup-token", "")
        if not provided or not constant_time_eq(settings.setup_token, provided):
            raise HTTPException(status_code=403, detail="Нужен токен первичной настройки")
    owner = Owner(
        username=payload.username.strip().lower(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip() or payload.username.strip(),
        last_login_at=utcnow(),
    )
    db.add(owner)
    db.flush()
    audit(db, owner.id, "owner.setup", target=owner.username)
    token, expires = _issue_session(db, owner, settings, request, "Первое устройство")
    return {"token": token, "expires_at": expires, "owner": _owner_public(owner)}


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: DbDep, settings: SettingsDep, limiter: LimiterDep) -> dict:
    ip = client_ip(request)
    enforce_rate_limit(limiter, f"login-ip:{ip}", settings.login_rate_limit, settings.login_rate_window,
                       "Слишком много попыток входа, попробуйте позже")
    enforce_rate_limit(limiter, f"login-user:{payload.username.lower()}",
                       settings.login_rate_limit, settings.login_rate_window,
                       "Слишком много попыток входа, попробуйте позже")
    owner = db.execute(select(Owner).where(Owner.username == payload.username.strip().lower())).scalar_one_or_none()
    if owner is None or not verify_password(payload.password, owner.password_hash):
        # не раскрываем, существует ли пользователь
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if not owner.is_active:
        raise HTTPException(status_code=403, detail="Владелец отключён")
    owner.last_login_at = utcnow()
    token, expires = _issue_session(db, owner, settings, request, payload.device_name or "Устройство")
    audit(db, owner.id, "owner.login", target=ip)
    return {"token": token, "expires_at": expires, "owner": _owner_public(owner)}


@router.get("/me")
def me(auth: OwnerDep) -> dict:
    return {"owner": _owner_public(auth.owner), "session_id": auth.session.id if auth.session else None}


@router.post("/logout")
def logout(auth: OwnerDep, db: DbDep) -> dict:
    if auth.session:
        auth.session.revoked_at = utcnow()
    return {"ok": True}


@router.get("/sessions")
def sessions(auth: OwnerDep, db: DbDep) -> dict:
    rows = db.execute(select(UserSession).where(UserSession.owner_id == auth.owner.id)
                      .order_by(UserSession.created_at.desc())).scalars().all()
    return {"sessions": [{
        "id": row.id, "device_id": row.device_id, "user_agent": row.user_agent,
        "created_at": row.created_at.isoformat() + "Z",
        "last_seen_at": row.last_seen_at.isoformat() + "Z",
        "revoked": row.revoked_at is not None,
        "current": auth.session is not None and row.id == auth.session.id,
    } for row in rows]}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, auth: OwnerDep, db: DbDep) -> dict:
    row = db.get(UserSession, session_id)
    if row is None or row.owner_id != auth.owner.id:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    row.revoked_at = utcnow()
    audit(db, auth.owner.id, "session.revoke", target=session_id)
    return {"ok": True}


@router.post("/sessions/revoke-all")
def revoke_all(auth: OwnerDep, db: DbDep) -> dict:
    rows = db.execute(select(UserSession).where(UserSession.owner_id == auth.owner.id,
                                               UserSession.revoked_at.is_(None))).scalars().all()
    now = utcnow()
    for row in rows:
        if auth.session and row.id == auth.session.id:
            continue
        row.revoked_at = now
    audit(db, auth.owner.id, "session.revoke_all")
    return {"ok": True, "revoked": len(rows) - 1}


@router.post("/password")
def change_password(payload: PasswordChange, auth: OwnerDep, db: DbDep) -> dict:
    if not verify_password(payload.current_password, auth.owner.password_hash):
        raise HTTPException(status_code=401, detail="Текущий пароль неверен")
    auth.owner.password_hash = hash_password(payload.new_password)
    rows = db.execute(select(UserSession).where(UserSession.owner_id == auth.owner.id,
                                               UserSession.revoked_at.is_(None))).scalars().all()
    for row in rows:
        if auth.session and row.id == auth.session.id:
            continue
        row.revoked_at = utcnow()
    audit(db, auth.owner.id, "owner.password_change")
    return {"ok": True}


def _issue_session(db, owner: Owner, settings, request: Request, device_name: str) -> tuple[str, str]:
    token = new_token()
    session = UserSession(
        owner_id=owner.id,
        token_hash=token_hash(token),
        user_agent=(request.headers.get("user-agent", "") or device_name)[:255],
        created_at=utcnow(),
        last_seen_at=utcnow(),
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.flush()
    return token, session.expires_at.isoformat() + "Z"


def _owner_public(owner: Owner) -> dict:
    return {"id": owner.id, "username": owner.username, "display_name": owner.display_name}
