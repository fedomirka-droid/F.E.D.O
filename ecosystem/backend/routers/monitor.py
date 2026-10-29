"""Мониторинг устройства (использует монитор F.E.D.O. Core)."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import APP_VERSION
from ..db import iso, utcnow
from ..deps import SettingsDep
from ..services import core_bridge

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/system")
def system(settings: SettingsDep) -> dict:
    snapshot = core_bridge.system_snapshot()
    return {
        "snapshot": snapshot,
        "summary": core_bridge.system_summary(),
        "core": {
            "available": core_bridge.core_available(),
            "version": core_bridge.core_version(),
            "build": core_bridge.core_build(),
        },
        "role": settings.role,
        "collected_at": iso(utcnow()),
    }


@router.get("/health")
def health(settings: SettingsDep) -> dict:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "edition": settings.edition,
        "role": settings.role,
        "core": core_bridge.core_version(),
        "time": iso(utcnow()),
    }
