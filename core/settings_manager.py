"""
F.E.D.O Core — Settings Manager (compat-модуль, v1.4)

Основной модуль настроек — core/settings.py.
Этот файл сохраняет единые точки импорта для будущего кода.
"""
from core.settings import (
    DEFAULT_SETTINGS,
    SETTINGS_FILE,
    load_settings,
    save_settings,
)

__all__ = ["DEFAULT_SETTINGS", "SETTINGS_FILE", "load_settings", "save_settings"]
