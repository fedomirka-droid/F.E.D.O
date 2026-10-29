"""Telegram: привязка аккаунта и API для бота F.E.D.O. Mini.

Разделение прав:
  * владелец (сессия) создаёт одноразовый код привязки;
  * бот (сервисный токен) может только «погасить» код и работать от имени
    привязанного Telegram-аккаунта;
  * Telegram ID сам по себе не даёт доступа ни к каким устройствам —
    только через запись TelegramAccount конкретного владельца.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import iso, utcnow
from ..deps import (DbDep, LimiterDep, OwnerDep, SettingsDep, audit, client_ip,
                    enforce_rate_limit, require_bot_service)
from ..models import (Device, ScheduleEntry, Task, TelegramAccount, TelegramLinkCode,
                      UserSession)
from ..security import (SecretBox, new_link_code, new_token, token_hash, verify_password)
from ..services import device_service, entities
from ..services.ai_router import AiRouter
from ..services.serializers import schedule_public, task_public
from .tasks import apply_action

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
bot = APIRouter(prefix="/api/bot", tags=["bot"], dependencies=[Depends(require_bot_service)])


class LinkResponse(BaseModel):
    code: str
    expires_at: str
    ttl_minutes: int


class BotLinkIn(BaseModel):
    code: str = Field(min_length=4, max_length=16)
    telegram_id: int
    username: str = Field(default="", max_length=64)


class BotTaskAction(BaseModel):
    telegram_id: int
    action: str
    minutes: int = Field(default=0, ge=0, le=600)


class BotAiIn(BaseModel):
    telegram_id: int
    message: str = Field(min_length=1, max_length=4000)
    mode: str | None = None


class BotTaskCreate(BaseModel):
    telegram_id: int
    title: str = Field(min_length=1, max_length=200)
    due_at: str | None = None
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")


class BotCommandIn(BaseModel):
    telegram_id: int
    action: str
    params: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Владелец: привязка
# --------------------------------------------------------------------------- #
@router.post("/link", response_model=LinkResponse)
def create_link(auth: OwnerDep, db: DbDep, settings: SettingsDep) -> LinkResponse:
    # инвалидируем прежние неиспользованные коды
    for row in db.execute(select(TelegramLinkCode).where(
            TelegramLinkCode.owner_id == auth.owner.id,
            TelegramLinkCode.used_at.is_(None))).scalars().all():
        db.delete(row)
    code = new_link_code()
    expires = utcnow() + timedelta(minutes=settings.telegram_link_ttl_minutes)
    db.add(TelegramLinkCode(owner_id=auth.owner.id, code_hash=token_hash(code), expires_at=expires))
    db.flush()
    audit(db, auth.owner.id, "telegram.link_code")  # сам код в аудит/логи не пишем
    return LinkResponse(code=code, expires_at=expires.isoformat() + "Z",
                        ttl_minutes=settings.telegram_link_ttl_minutes)


@router.get("/accounts")
def accounts(auth: OwnerDep, db: DbDep) -> dict:
    rows = db.execute(select(TelegramAccount).where(TelegramAccount.owner_id == auth.owner.id)).scalars().all()
    return {"accounts": [{"id": row.id, "telegram_id": row.telegram_id, "username": row.username,
                          "linked_at": iso(row.linked_at), "revoked": row.revoked_at is not None}
                         for row in rows]}


@router.delete("/accounts/{account_id}")
def unlink(account_id: int, auth: OwnerDep, db: DbDep) -> dict:
    row = db.get(TelegramAccount, account_id)
    if row is None or row.owner_id != auth.owner.id:
        raise HTTPException(status_code=404, detail="Привязка не найдена")
    row.revoked_at = utcnow()
    db.flush()
    audit(db, auth.owner.id, "telegram.unlink", target=str(row.telegram_id))
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Бот: привязка и данные
# --------------------------------------------------------------------------- #
def _owner_for_telegram(db, telegram_id: int) -> str:
    account = db.execute(select(TelegramAccount).where(
        TelegramAccount.telegram_id == telegram_id,
        TelegramAccount.revoked_at.is_(None))).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=403,
                            detail="Аккаунт Telegram не привязан. Открой Desktop → Настройки → Telegram")
    return account.owner_id


@bot.post("/link")
def claim_link(payload: BotLinkIn, db: DbDep, settings: SettingsDep, limiter: LimiterDep) -> dict:
    enforce_rate_limit(limiter, f"tg-link:{payload.telegram_id}", 5, 300, "Слишком много попыток привязки")
    code_hash = token_hash(payload.code.strip().upper())
    row = db.execute(select(TelegramLinkCode).where(TelegramLinkCode.code_hash == code_hash)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Код не найден")
    if row.used_at is not None:
        raise HTTPException(status_code=409, detail="Код уже использован")
    if row.expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="Срок действия кода истёк")
    if row.attempts >= settings.telegram_link_max_attempts:
        raise HTTPException(status_code=429, detail="Слишком много попыток для этого кода")
    row.attempts += 1
    row.used_at = utcnow()
    row.claimed_by = payload.telegram_id
    existing = db.execute(select(TelegramAccount).where(
        TelegramAccount.telegram_id == payload.telegram_id)).scalar_one_or_none()
    if existing is not None:
        existing.revoked_at = None
        existing.owner_id = row.owner_id
        existing.username = payload.username
    else:
        db.add(TelegramAccount(owner_id=row.owner_id, telegram_id=payload.telegram_id,
                               username=payload.username))
    db.flush()
    audit(db, row.owner_id, "telegram.linked", actor="telegram", telegram_id=payload.telegram_id)
    return {"ok": True, "linked": True, "owner_id": row.owner_id}


@bot.get("/accounts")
def bot_accounts(db: DbDep) -> dict:
    """Служебно: привязанные аккаунты (для цикла напоминаний бота)."""
    rows = db.execute(select(TelegramAccount).where(
        TelegramAccount.revoked_at.is_(None))).scalars().all()
    return {"accounts": [{"telegram_id": row.telegram_id, "owner_id": row.owner_id}
                         for row in rows]}


@bot.get("/today")
def bot_today(telegram_id: int, db: DbDep) -> dict:
    from ..services.serializers import task_public as tp

    owner_id = _owner_for_telegram(db, telegram_id)
    from datetime import date

    today = date.today().isoformat()
    tasks = db.execute(select(Task).where(Task.owner_id == owner_id, Task.deleted_at.is_(None))).scalars().all()
    lessons = db.execute(select(ScheduleEntry).where(
        ScheduleEntry.owner_id == owner_id, ScheduleEntry.deleted_at.is_(None),
        ScheduleEntry.date == today)).scalars().all()
    active = [t for t in tasks if t.status not in ("done", "skipped")]
    return {"date": today, "tasks": [tp(t) for t in active[:10]],
            "lessons": [schedule_public(e) for e in sorted(lessons, key=lambda e: (e.slot, e.start_time))]}


@bot.get("/tasks")
def bot_tasks(telegram_id: int, db: DbDep) -> dict:
    owner_id = _owner_for_telegram(db, telegram_id)
    rows = db.execute(select(Task).where(Task.owner_id == owner_id, Task.deleted_at.is_(None))
                      .order_by(Task.due_at.is_(None), Task.due_at).limit(30)).scalars().all()
    return {"tasks": [task_public(t) for t in rows]}


@bot.post("/tasks")
def bot_create_task(payload: BotTaskCreate, db: DbDep, settings: SettingsDep) -> dict:
    owner_id = _owner_for_telegram(db, payload.telegram_id)
    task = entities.create_entity(db, settings, owner_id, "task", {
        "title": payload.title, "due_at": payload.due_at, "priority": payload.priority,
        "status": "todo",
    })
    audit(db, owner_id, "telegram.task.create", target=task.id, actor="telegram")
    return task_public(task)


@bot.get("/reminders")
def bot_reminders(telegram_id: int, db: DbDep, window_minutes: int = 60) -> dict:
    """Напоминания для бота: задачи с наступившим remind_at/due_at."""
    from datetime import timedelta

    owner_id = _owner_for_telegram(db, telegram_id)
    now = utcnow()
    horizon = now + timedelta(minutes=window_minutes)
    rows = db.execute(select(Task).where(Task.owner_id == owner_id,
                                         Task.deleted_at.is_(None))).scalars().all()
    reminders = []
    for task in rows:
        if task.status in ("done", "skipped"):
            continue
        moment = task.remind_at or task.due_at
        if moment and now - timedelta(minutes=10) <= moment <= horizon:
            reminders.append({"task": task_public(task), "at": iso(moment)})
    return {"reminders": reminders, "now": iso(now)}


@bot.get("/schedule")
def bot_schedule(telegram_id: int, db: DbDep, day: str = "today") -> dict:
    from datetime import date, timedelta

    owner_id = _owner_for_telegram(db, telegram_id)
    target = date.today() if day != "tomorrow" else date.today() + timedelta(days=1)
    rows = db.execute(select(ScheduleEntry).where(
        ScheduleEntry.owner_id == owner_id, ScheduleEntry.deleted_at.is_(None),
        ScheduleEntry.date == target.isoformat())).scalars().all()
    return {"date": target.isoformat(), "day": day,
            "entries": [schedule_public(e) for e in sorted(rows, key=lambda e: (e.slot, e.start_time))]}


@bot.get("/devices")
def bot_devices(telegram_id: int, db: DbDep) -> dict:
    owner_id = _owner_for_telegram(db, telegram_id)
    rows = db.execute(select(Device).where(Device.owner_id == owner_id)).scalars().all()
    from .devices import _effective_status

    return {"devices": [{"id": d.id, "name": d.name, "kind": d.kind,
                         "status": _effective_status(d), "ai_available": d.ai_available,
                         "last_seen_at": iso(d.last_seen_at)} for d in rows],
            "actions": device_service.action_catalog()}


@bot.get("/status")
def bot_status(telegram_id: int, db: DbDep, settings: SettingsDep) -> dict:
    owner_id = _owner_for_telegram(db, telegram_id)
    devices = db.execute(select(Device).where(Device.owner_id == owner_id)).scalars().all()
    from .devices import _effective_status

    online = [d.name for d in devices if _effective_status(d) == "online"]
    router_ = AiRouter(db, settings, SecretBox(settings.secret_key))
    usage = router_.usage_summary(owner_id)
    return {"devices_total": len(devices), "devices_online": online,
            "ai_mode": router_.ai_settings(owner_id).mode,
            "ai_usage": usage, "sync_enabled": settings.sync_enabled}


@bot.post("/tasks/{task_id}/action")
def bot_task_action(task_id: str, payload: BotTaskAction, db: DbDep, settings: SettingsDep) -> dict:
    owner_id = _owner_for_telegram(db, payload.telegram_id)
    task = db.get(Task, task_id)
    if task is None or task.owner_id != owner_id or task.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    try:
        apply_action(db, settings, owner_id, task, payload.action, payload.minutes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, owner_id, f"telegram.task.{payload.action}", target=task_id, actor="telegram")
    return task_public(task)


@bot.post("/devices/{device_id}/command")
def bot_command(device_id: str, payload: BotCommandIn, db: DbDep, settings: SettingsDep) -> dict:
    owner_id = _owner_for_telegram(db, payload.telegram_id)
    device = db.get(Device, device_id)
    if device is None or device.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    secret = SecretBox(settings.secret_key).decrypt(device.channel_secret_enc or "")
    try:
        command = device_service.create_command(
            db, owner_id, device, payload.action, payload.params,
            requested_by="telegram", requested_by_id=str(payload.telegram_id),
            channel_secret=secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, owner_id, "telegram.device.command", target=f"{device.name}:{payload.action}",
          actor="telegram", command_id=command.id,
          requires_confirmation=command.requires_confirmation)
    return {"id": command.id, "action": command.action, "status": command.status,
            "requires_confirmation": command.requires_confirmation,
            "note": ("Требуется подтверждение в Desktop" if command.requires_confirmation
                     else "Команда отправлена устройству")}


@bot.post("/ai")
async def bot_ai(payload: BotAiIn, db: DbDep, settings: SettingsDep, request: Request,
                 limiter: LimiterDep) -> dict:
    owner_id = _owner_for_telegram(db, payload.telegram_id)
    enforce_rate_limit(limiter, f"tg-ai:{payload.telegram_id}", 20, 60, "Слишком много AI-запросов")
    router_ = AiRouter(db, settings, SecretBox(settings.secret_key),
                       cancel_registry=request.app.state.ai_cancels)
    result = await router_.chat(owner_id, payload.message, mode=payload.mode)
    return {"text": result.text, "provider": result.provider, "model": result.model,
            "cloud": result.cloud, "usage": {"cost": round(result.cost, 6)},
            "trace": result.trace}
