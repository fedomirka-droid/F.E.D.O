"""Доступ к БД: engine, сессии, миграции с резервной копией."""
from __future__ import annotations

import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Settings


def utcnow() -> datetime:
    """Naive UTC — единый формат хранения (SQLite не хранит tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso(dt: datetime | None) -> str | None:
    """ISO-8601 с Z для API/синхронизации."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat() + "Z"


class Base(DeclarativeBase):
    pass


def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def make_engine(url: str, echo: bool = False) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


class Database:
    """Тонкая обёртка вокруг engine + sessionmaker."""

    def __init__(self, settings: Settings, echo: bool = False):
        self.settings = settings
        self.engine = make_engine(settings.database_url, echo=echo)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    @contextmanager
    def session(self) -> Session:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_all(self) -> None:
        """Только для тестов: схема из метаданных без alembic."""
        from . import models  # noqa: F401  (регистрация таблиц)

        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()


def backup_sqlite(sqlite_path: Path, backup_dir: Path) -> Path | None:
    """Копия файла БД перед миграцией (SQLite Backup API недоступен без открытия)."""
    if not sqlite_path.exists() or sqlite_path.stat().st_size == 0:
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"pre-migrate-{stamp}-{sqlite_path.name}"
    shutil.copy2(sqlite_path, target)
    return target


def run_migrations(settings: Settings) -> dict:
    """Alembic upgrade head с предварительной резервной копией SQLite."""
    from alembic import command
    from alembic.config import Config

    pkg_dir = Path(__file__).resolve().parent
    backup = None
    if settings.sqlite_path:
        backup = backup_sqlite(settings.sqlite_path, settings.data_path / "backups")

    cfg = Config(str(pkg_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(pkg_dir / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    return {"backup": str(backup) if backup else None, "database": settings.database_url}
