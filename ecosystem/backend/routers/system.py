"""Системные операции владельца: резервная копия базы, состояние HUB.

Копия делается через sqlite3 backup API, а не копированием файла: при WAL
простое копирование даёт неполную схему. Восстановление — отдельная команда
в scripts/ubuntu/restore-hub.sh; из API базу не подменяем, чтобы не сломать
работающий процесс из-под него самого.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import APP_VERSION
from ..db import utcnow
from ..deps import DbDep, OwnerDep, SettingsDep, audit

router = APIRouter(prefix="/api/system", tags=["system"])

MAX_BACKUPS = 20


def _db_path(settings) -> Path:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise HTTPException(status_code=400, detail="Резервное копирование поддерживается для SQLite")
    return Path(url.replace("sqlite:///", "", 1))


def _backup_dir(settings) -> Path:
    directory = Path(settings.data_dir) / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.post("/backup")
def make_backup(auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    """Создать согласованную копию базы. Работает и на HUB, и на Desktop."""
    source_path = _db_path(settings)
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail="Файл базы не найден")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = _backup_dir(settings) / f"fedo-{stamp}.db"

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        with destination:
            source.backup(destination)
    finally:
        source.close()
        destination.close()

    # проверяем, что копия читается и содержит ключевую таблицу
    check = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in check.execute(
            "select name from sqlite_master where type='table'").fetchall()}
    finally:
        check.close()
    if "owners" not in tables:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Копия получилась неполной — удалена")

    size = target.stat().st_size
    checksum = _checksum(target)
    audit(db, auth.owner.id, "system.backup", target=str(target), size=size)

    backups = sorted(_backup_dir(settings).glob("fedo-*.db"), reverse=True)
    for old in backups[MAX_BACKUPS:]:
        old.unlink(missing_ok=True)

    return {"ok": True, "path": str(target), "size": size, "checksum": checksum,
            "created_at": utcnow().isoformat() + "Z"}


@router.get("/backups")
def list_backups(auth: OwnerDep, settings: SettingsDep) -> dict:
    directory = _backup_dir(settings)
    items = []
    for path in sorted(directory.glob("fedo-*.db"), reverse=True)[:MAX_BACKUPS]:
        stat = path.stat()
        items.append({
            "name": path.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            .replace(microsecond=0).isoformat() + "Z",
        })
    return {"backups": items, "directory": str(directory)}


@router.get("/info")
def system_info(auth: OwnerDep, settings: SettingsDep) -> dict:
    """Где работает узел и куда он синхронизируется — для экрана «Настройки»."""
    return {
        "version": APP_VERSION,
        "role": settings.role.value if hasattr(settings.role, "value") else str(settings.role),
        "is_hub": settings.is_hub,
        "data_dir": str(settings.data_dir),
        "hub_url": settings.hub_url or "",
        "sync_enabled": bool(settings.sync_enabled),
        "telegram_configured": bool(settings.telegram_bot_token),
        "local_ai_url": settings.local_ai_url,
        "backup_dir": str(_backup_dir(settings)),
    }
