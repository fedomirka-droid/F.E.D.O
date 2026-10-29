"""FastAPI-приложение Ecosystem (одна кодовая база: HUB и Desktop-бэкенд)."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select

from .config import APP_VERSION, Settings, get_settings
from .db import Database, run_migrations
from .routers import (ai, auth, calendar, devices, monitor, preferences, schedule,
                      sync, tasks, telegram)
from .security import RateLimiter, redact

logger = logging.getLogger("fedo")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


class SyncLoop:
    """Фоновый поток синхронизации Desktop → HUB (не блокирует API)."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_result: dict = {}

    def start(self) -> None:
        settings: Settings = self.app.state.settings
        if settings.is_hub or not settings.sync_enabled or not settings.hub_url:
            return
        self.thread = threading.Thread(target=self._run, name="fedo-sync", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        settings: Settings = self.app.state.settings
        from .models import Owner
        from .services.sync_worker import run_sync

        while not self.stop_event.is_set():
            try:
                with self.app.state.db.session() as db:
                    owner = db.execute(select(Owner)).scalars().first()
                    if owner is not None:
                        result = run_sync(db, settings, owner.id)
                        self.last_result = result
                        if result.get("ok"):
                            logger.info("sync ok: pushed=%s pulled=%s", result.get("pushed"),
                                        result.get("pulled"))
            except Exception as exc:  # поток не должен умирать
                logger.warning("sync loop error: %s", redact(str(exc)))
            self.stop_event.wait(settings.sync_interval_seconds)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)


def create_app(settings: Settings | None = None, db: Database | None = None,
               auto_migrate: bool | None = None, start_sync: bool = True) -> FastAPI:
    settings = settings or get_settings()
    database = db or Database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if auto_migrate is None:
            # тесты создают схему через create_all (auto_migrate=False),
            # в реальном запуске схему поднимает alembic с бэкапом SQLite
            if settings.database_url.startswith("sqlite"):
                try:
                    info = await asyncio.to_thread(run_migrations, settings)
                    logger.info("migrations applied: %s", info.get("backup"))
                except Exception as exc:
                    logger.error("migration failed: %s", redact(str(exc)))
                    raise
        loop = SyncLoop(app)
        app.state.sync_loop = loop
        if start_sync and settings.role == "desktop":
            loop.start()
        yield
        loop.stop()
        database.close()

    app = FastAPI(
        title="F.E.D.O. Ecosystem HUB",
        version=APP_VERSION,
        description="Personal Edition — HUB / локальный бэкенд Desktop",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = database
    app.state.limiter = RateLimiter()
    app.state.ai_cancels = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Device-Token", "X-Bot-Token",
                       "X-Setup-Token", "X-FEDO-Device", "X-FEDO-Signature", "X-FEDO-Timestamp"],
    )

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/health", "/api/monitor/health"):
            ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                  or (request.client.host if request.client else "unknown"))
            allowed, retry = app.state.limiter.hit(f"api:{ip}", settings.api_rate_limit,
                                                   settings.api_rate_window)
            if not allowed:
                return JSONResponse({"detail": "Слишком много запросов"},
                                    status_code=429, headers={"Retry-After": str(retry)})
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - started) * 1000
        if path.startswith("/api/") and elapsed > 1500:
            logger.info("slow api: %s %.0fms", path, elapsed)
        return response

    for module in (auth.router, tasks.router, calendar.router, schedule.router,
                   devices.router, devices.agent_router, sync.router, ai.router,
                   monitor.router, preferences.router, telegram.router, telegram.bot):
        app.include_router(module)

    @app.get("/api/health")
    def health() -> dict:
        from .services import core_bridge

        return {
            "status": "ok",
            "version": APP_VERSION,
            "edition": settings.edition,
            "role": settings.role,
            "core": core_bridge.core_version(),
            "sync": {"enabled": settings.sync_enabled, "hub_configured": bool(settings.hub_url)},
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                            headers=exc.headers or {})

    # --- раздача собранного frontend (Tauri/Desktop) --------------------- #
    dist = settings.frontend_dir if settings.serve_frontend else None
    if dist:
        assets = Path(dist) / "assets"

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(Path(dist) / "index.html")

        @app.get("/assets/{asset_path:path}", include_in_schema=False)
        def asset(asset_path: str) -> FileResponse:
            target = (assets / asset_path).resolve()
            if not str(target).startswith(str(assets.resolve())) or not target.exists():
                raise HTTPException(status_code=404, detail="asset not found")
            return FileResponse(target)

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            candidate = (Path(dist) / full_path).resolve()
            if full_path and str(candidate).startswith(str(Path(dist).resolve())) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(Path(dist) / "index.html")

    return app


app = create_app()
