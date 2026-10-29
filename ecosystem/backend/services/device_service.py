"""Device Manager: реестр устройств и строго типизированные команды.

Модель безопасности:
  * действия — только из белого списка ACTIONS (никакого free-form shell);
  * параметры нормализуются (whitelist), опасные действия требуют подтверждения;
  * команда подписывается HMAC секретом канала устройства;
  * каждое управляющее действие пишется в audit_log.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Device, DeviceCommand
from ..security import sign_payload

MAX_STR = 200


@dataclass(frozen=True)
class ActionSpec:
    name: str
    dangerous: bool
    description: str
    params: tuple[str, ...] = ()


ACTIONS: dict[str, ActionSpec] = {
    "status": ActionSpec("status", False, "Получить статус устройства"),
    "stats": ActionSpec("stats", False, "Получить системную статистику"),
    "ai_check": ActionSpec("ai_check", False, "Проверить доступность локального AI"),
    "ai_start": ActionSpec("ai_start", True, "Запустить разрешённый AI-сервис"),
    "ai_stop": ActionSpec("ai_stop", True, "Остановить разрешённый AI-сервис"),
    "sleep": ActionSpec("sleep", True, "Отправить компьютер в сон"),
    "wol": ActionSpec("wol", True, "Разбудить ПК через Wake-on-LAN", params=("mac", "broadcast")),
}

FORBIDDEN_HINTS = ("shell", "cmd", "powershell", "bash", "exec", "sudo", "rm ", "del ")


def action_catalog() -> list[dict]:
    return [
        {"action": a.name, "dangerous": a.dangerous, "description": a.description,
         "params": list(a.params)}
        for a in ACTIONS.values()
    ]


def validate_action(action: str, params: dict | None = None) -> tuple[ActionSpec, dict]:
    """Проверить действие/параметры. Любое отклонение — ValueError."""
    if not action or action not in ACTIONS:
        raise ValueError(f"Действие «{action}» не разрешено")
    lowered = str(action).lower()
    if any(hint in lowered for hint in FORBIDDEN_HINTS):
        raise ValueError("Свободное выполнение команд запрещено")
    spec = ACTIONS[action]
    incoming = params or {}
    if not isinstance(incoming, dict):
        raise ValueError("Параметры должны быть объектом")
    unknown = set(incoming) - set(spec.params)
    if unknown:
        raise ValueError(f"Недопустимые параметры: {', '.join(sorted(unknown))}")
    clean: dict[str, Any] = {}
    for key in spec.params:
        value = incoming.get(key)
        if value is None:
            continue
        if not isinstance(value, (str, int, float)):
            raise ValueError(f"Параметр «{key}» имеет недопустимый тип")
        text = str(value).strip()
        if len(text) > MAX_STR:
            raise ValueError(f"Параметр «{key}» слишком длинный")
        clean[key] = text
    return spec, clean


def create_command(db: Session, owner_id: str, device: Device, action: str,
                   params: dict | None, requested_by: str = "desktop",
                   requested_by_id: str = "", channel_secret: str = "",
                   force_confirm: bool | None = None) -> DeviceCommand:
    spec, clean = validate_action(action, params)
    if device.revoked_at is not None:
        raise ValueError("Устройство отозвано")
    needs_confirm = spec.dangerous if force_confirm is None else force_confirm
    command = DeviceCommand(
        id=str(uuid.uuid4()), owner_id=owner_id, device_id=device.id, action=spec.name,
        params=clean, status="awaiting_confirmation" if needs_confirm else "approved",
        requires_confirmation=needs_confirm, requested_by=requested_by,
        requested_by_id=str(requested_by_id)[:64],
    )
    if not needs_confirm and channel_secret:
        command.signature = sign_payload(channel_secret, command_payload(command))
    db.add(command)
    db.flush()
    return command


def command_payload(command: DeviceCommand) -> dict:
    return {
        "command_id": command.id,
        "device_id": command.device_id,
        "action": command.action,
        "params": command.params or {},
    }


def confirm_command(db: Session, owner_id: str, device: Device, command: DeviceCommand,
                    channel_secret: str) -> DeviceCommand:
    if command.owner_id != owner_id or command.device_id != device.id:
        raise PermissionError("Команда принадлежит другому устройству")
    if command.status not in ("awaiting_confirmation", "approved"):
        return command
    command.status = "approved"
    command.confirmed_at = utcnow()
    command.signature = sign_payload(channel_secret, command_payload(command))
    db.flush()
    return command


def reject_command(command: DeviceCommand) -> DeviceCommand:
    command.status = "rejected"
    command.finished_at = utcnow()
    return command


def pending_for_device(db: Session, device: Device, channel_secret: str) -> list[dict]:
    rows = db.execute(
        select(DeviceCommand).where(
            DeviceCommand.device_id == device.id,
            DeviceCommand.status == "approved",
        ).order_by(DeviceCommand.created_at)
    ).scalars().all()
    out = []
    for command in rows:
        payload = command_payload(command)
        if not command.signature:
            command.signature = sign_payload(channel_secret, payload)
        command.status = "sent"
        command.delivered_at = utcnow()
        out.append({**payload, "signature": command.signature,
                    "requires_confirmation": command.requires_confirmation})
    db.flush()
    return out


def finish_command(db: Session, device: Device, command_id: str, ok: bool,
                   result: dict | None = None) -> DeviceCommand | None:
    command = db.get(DeviceCommand, command_id)
    if command is None or command.device_id != device.id:
        return None
    command.status = "done" if ok else "failed"
    command.result = result or {}
    command.finished_at = utcnow()
    db.flush()
    return command


def device_public(device: Device) -> dict:
    from ..db import iso

    return {
        "id": device.id,
        "name": device.name,
        "kind": device.kind,
        "platform": device.platform,
        "status": device.status,
        "ai_available": device.ai_available,
        "capabilities": device.capabilities or [],
        "metrics": device.metrics or {},
        "last_seen_at": iso(device.last_seen_at),
        "notes": device.notes,
        "revoked": device.revoked_at is not None,
    }
