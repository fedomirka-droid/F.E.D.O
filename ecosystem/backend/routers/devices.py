"""Device Manager + канал управления агентом."""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import iso, utcnow
from ..deps import DbDep, DeviceDep, OwnerDep, SettingsDep, audit
from ..models import Device, DeviceCommand
from ..security import SecretBox, new_token, token_hash, verify_signature
from ..services import device_service
from ..services.serializers import device_summary

router = APIRouter(prefix="/api/devices", tags=["devices"])
agent_router = APIRouter(prefix="/api/agent", tags=["agent"])

ONLINE_WINDOW = timedelta(seconds=90)


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="desktop", pattern="^(desktop|gpu|hub|controller)$")
    platform: str = Field(default="", max_length=120)
    capabilities: list[str] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=255)


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    capabilities: list[str] | None = None
    notes: str | None = Field(default=None, max_length=255)


class CommandCreate(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)


def _owned_device(db, owner_id: str, device_id: str) -> Device:
    device = db.get(Device, device_id)
    if device is None or device.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    return device


def _effective_status(device: Device) -> str:
    if device.revoked_at is not None:
        return "revoked"
    if device.status == "sleeping":
        return "sleeping"
    if device.last_seen_at and utcnow() - device.last_seen_at <= ONLINE_WINDOW:
        return "online"
    return "offline"


# --------------------------------------------------------------------------- #
# Владелец
# --------------------------------------------------------------------------- #
@router.get("")
def list_devices(auth: OwnerDep, db: DbDep) -> dict:
    rows = db.execute(select(Device).where(Device.owner_id == auth.owner.id)
                      .order_by(Device.created_at)).scalars().all()
    devices = []
    for device in rows:
        data = device_summary(device)
        data["status"] = _effective_status(device)
        data["pending_commands"] = db.execute(
            select(DeviceCommand).where(DeviceCommand.device_id == device.id,
                                        DeviceCommand.status.in_(("approved", "awaiting_confirmation", "sent")))
        ).scalars().all()
        data["pending_commands"] = len(data["pending_commands"])
        devices.append(data)
    return {"devices": devices, "actions": device_service.action_catalog()}


@router.post("")
def register_device(payload: DeviceCreate, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    exists = db.execute(select(Device).where(Device.owner_id == auth.owner.id,
                                             Device.name == payload.name)).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="Устройство с таким именем уже есть")
    token = new_token("dev_")
    channel_secret = new_token()
    box = SecretBox(settings.secret_key)
    device = Device(
        id=str(uuid.uuid4()), owner_id=auth.owner.id, name=payload.name.strip(),
        kind=payload.kind, platform=payload.platform, token_hash=token_hash(token),
        channel_secret_enc=box.encrypt(channel_secret), capabilities=payload.capabilities,
        notes=payload.notes, status="offline",
    )
    db.add(device)
    db.flush()
    audit(db, auth.owner.id, "device.register", target=device.id, name=device.name)
    # токен и секрет канала показываются ОДИН раз
    return {"device": device_summary(device), "token": token, "channel_secret": channel_secret,
            "warning": "Сохрани токен и секрет: они больше не будут показаны"}


@router.patch("/{device_id}")
def update_device(device_id: str, payload: DeviceUpdate, auth: OwnerDep, db: DbDep) -> dict:
    device = _owned_device(db, auth.owner.id, device_id)
    if payload.name is not None:
        device.name = payload.name.strip()
    if payload.capabilities is not None:
        device.capabilities = payload.capabilities
    if payload.notes is not None:
        device.notes = payload.notes
    db.flush()
    return device_summary(device)


@router.post("/{device_id}/rotate-token")
def rotate_token(device_id: str, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    device = _owned_device(db, auth.owner.id, device_id)
    token = new_token("dev_")
    secret = new_token()
    device.token_hash = token_hash(token)
    device.channel_secret_enc = SecretBox(settings.secret_key).encrypt(secret)
    db.flush()
    audit(db, auth.owner.id, "device.rotate_token", target=device.id)
    return {"token": token, "channel_secret": secret,
            "warning": "Старые токен и секрет больше не действуют"}


@router.post("/{device_id}/revoke")
def revoke_device(device_id: str, auth: OwnerDep, db: DbDep) -> dict:
    device = _owned_device(db, auth.owner.id, device_id)
    device.revoked_at = utcnow()
    device.status = "offline"
    db.flush()
    audit(db, auth.owner.id, "device.revoke", target=device.id)
    return {"ok": True}


@router.get("/{device_id}/commands")
def list_commands(device_id: str, auth: OwnerDep, db: DbDep,
                  limit: int = Query(default=50, ge=1, le=200)) -> dict:
    _owned_device(db, auth.owner.id, device_id)
    rows = db.execute(select(DeviceCommand).where(DeviceCommand.device_id == device_id)
                      .order_by(DeviceCommand.created_at.desc()).limit(limit)).scalars().all()
    return {"commands": [_command_public(c) for c in rows]}


@router.post("/{device_id}/commands")
def send_command(device_id: str, payload: CommandCreate, auth: OwnerDep, db: DbDep,
                 settings: SettingsDep) -> dict:
    device = _owned_device(db, auth.owner.id, device_id)
    secret = SecretBox(settings.secret_key).decrypt(device.channel_secret_enc or "")
    try:
        command = device_service.create_command(
            db, auth.owner.id, device, payload.action, payload.params,
            requested_by="desktop", requested_by_id=auth.owner.username,
            channel_secret=secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, auth.owner.id, "device.command", target=f"{device.name}:{payload.action}",
          command_id=command.id, requires_confirmation=command.requires_confirmation)
    return _command_public(command)


@router.post("/commands/{command_id}/confirm")
def confirm(command_id: str, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    command = db.get(DeviceCommand, command_id)
    if command is None or command.owner_id != auth.owner.id:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    device = _owned_device(db, auth.owner.id, command.device_id)
    secret = SecretBox(settings.secret_key).decrypt(device.channel_secret_enc or "")
    device_service.confirm_command(db, auth.owner.id, device, command, secret)
    audit(db, auth.owner.id, "device.command.confirm", target=command.id)
    return _command_public(command)


@router.post("/commands/{command_id}/reject")
def reject(command_id: str, auth: OwnerDep, db: DbDep) -> dict:
    command = db.get(DeviceCommand, command_id)
    if command is None or command.owner_id != auth.owner.id:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    device_service.reject_command(command)
    audit(db, auth.owner.id, "device.command.reject", target=command.id)
    return _command_public(command)


# --------------------------------------------------------------------------- #
# Агент (device token)
# --------------------------------------------------------------------------- #
class Heartbeat(BaseModel):
    status: str = Field(default="online", pattern="^(online|offline|sleeping)$")
    metrics: dict = Field(default_factory=dict)
    ai_available: bool = False
    platform: str = Field(default="", max_length=120)


@agent_router.post("/heartbeat")
def heartbeat(payload: Heartbeat, device: DeviceDep, db: DbDep) -> dict:
    device.status = payload.status
    device.metrics = payload.metrics
    device.ai_available = payload.ai_available
    device.last_seen_at = utcnow()
    if payload.platform:
        device.platform = payload.platform
    db.flush()
    return {"ok": True, "server_time": iso(utcnow())}


@agent_router.get("/poll")
def poll(device: DeviceDep, db: DbDep, settings: SettingsDep) -> dict:
    from ..security import SecretBox

    secret = SecretBox(settings.secret_key).decrypt(device.channel_secret_enc or "")
    commands = device_service.pending_for_device(db, device, secret)
    return {"commands": commands, "server_time": iso(utcnow())}


class CommandResult(BaseModel):
    command_id: str
    ok: bool
    result: dict = Field(default_factory=dict)


@agent_router.post("/result")
def report_result(payload: CommandResult, device: DeviceDep, db: DbDep) -> dict:
    command = db.get(DeviceCommand, payload.command_id)
    if command is None or command.device_id != device.id:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    # устройство аутентифицировано по собственному токену — этого достаточно
    device_service.finish_command(db, device, payload.command_id, payload.ok, payload.result)
    audit(db, device.owner_id, "device.command.result", target=payload.command_id,
          actor=f"device:{device.name}", ok=payload.ok)
    return {"ok": True}


def _command_public(command: DeviceCommand) -> dict:
    return {
        "id": command.id, "device_id": command.device_id, "action": command.action,
        "params": command.params, "status": command.status,
        "requires_confirmation": command.requires_confirmation,
        "requested_by": command.requested_by, "result": command.result,
        "created_at": iso(command.created_at), "confirmed_at": iso(command.confirmed_at),
        "delivered_at": iso(command.delivered_at), "finished_at": iso(command.finished_at),
    }
