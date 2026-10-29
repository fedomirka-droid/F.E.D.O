"""Конфигурация Ecosystem Personal Edition (переменные окружения FEDO_*)."""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "2.0.0-personal"


def default_data_dir() -> Path:
    """Стандартная директория данных приложения.

    Windows: %APPDATA%\\FEDO\\. Linux: ~/.local/share/fedo.
    Переопределяется FEDO_DATA_DIR (используется в тестах и в HUB-контейнере).
    """
    override = os.environ.get("FEDO_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "FEDO"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "fedo"
    return Path.home() / ".local" / "share" / "fedo"


def _load_or_create_secret(data_dir: Path) -> str:
    """Секрет приложения: env → файл в data_dir (0600) → новый.

    В Git секреты не попадают: файл лежит в профиле пользователя.
    """
    path = data_dir / "secret.key"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(48)
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


class Settings(BaseSettings):
    """Настройки HUB и Desktop-бэкенда (один код — две роли)."""

    model_config = SettingsConfigDict(env_prefix="FEDO_", env_file=".env", extra="ignore")

    role: Literal["hub", "desktop"] = "desktop"
    app_name: str = "F.E.D.O. Ecosystem"
    edition: str = "Personal"

    data_dir: str = ""
    database_url: str = ""
    secret_key: str = ""

    host: str = "127.0.0.1"
    port: int = 8765

    # Безопасность
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,tauri://localhost,http://tauri.localhost"
    allow_public_registration: bool = False
    session_ttl_hours: int = 720
    login_rate_limit: int = 10
    login_rate_window: int = 60
    # Токен сервиса Telegram-бота (HUB проверяет его у bot-эндпоинтов)
    bot_service_token: str = ""
    # Необязательный токен первичной настройки владельца (для HUB в интернете)
    setup_token: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_link_ttl_minutes: int = 10
    telegram_link_max_attempts: int = 5

    # HUB-адрес для Desktop (синхронизация). Пусто — работаем только локально.
    hub_url: str = ""
    sync_device_token: str = ""
    sync_enabled: bool = True
    sync_interval_seconds: int = 15
    sync_request_timeout: float = 10.0

    # AI Router
    local_ai_url: str = "http://127.0.0.1:1234/v1"
    ai_request_timeout: float = 120.0
    ai_connect_timeout: float = 5.0

    # Ограничение запросов API
    api_rate_limit: int = 240
    api_rate_window: int = 60

    # Раздача собранного frontend (Tauri/Desktop)
    serve_frontend: bool = True
    frontend_dist: str = ""

    extra: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _finalize(self) -> "Settings":
        if not self.data_dir:
            self.data_dir = str(default_data_dir())
        path = Path(self.data_dir)
        for sub in ("", "backups", "logs", "uploads", "ai_exports"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        if not self.secret_key:
            self.secret_key = _load_or_create_secret(path)
        if not self.database_url:
            self.database_url = f"sqlite:///{path / 'fedo.db'}"
        return self

    # --- производные значения -------------------------------------------------
    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_hub(self) -> bool:
        return self.role == "hub"

    @property
    def sqlite_path(self) -> Path | None:
        url = self.database_url
        if url.startswith("sqlite:///"):
            return Path(url[len("sqlite:///"):])
        return None

    @property
    def frontend_dir(self) -> Path | None:
        if self.frontend_dist:
            p = Path(self.frontend_dist)
            return p if p.exists() else None
        candidate = Path(__file__).resolve().parents[2] / "desktop" / "dist"
        return candidate if candidate.exists() else None


def get_settings(**overrides) -> Settings:
    """Свежие настройки (не кэшируем: тесты изолируют data_dir)."""
    return Settings(**overrides)
