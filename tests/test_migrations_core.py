"""Проверки 17–20: миграции, совместимость с F.E.D.O. Core, запуск/перезапуск."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from ecosystem.backend.config import Settings
from ecosystem.backend.db import Base, run_migrations

ROOT = Path(__file__).resolve().parents[1]


def test_migrations_create_schema_and_backup(tmp_path):
    settings = Settings(data_dir=str(tmp_path), role="hub",
                        database_url=f"sqlite:///{tmp_path}/hub.db",
                        secret_key="migration-test-secret")
    first = run_migrations(settings)
    assert first["backup"] is None  # базы ещё не было
    engine = create_engine(settings.database_url)
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables).issubset(tables)
    assert "alembic_version" in tables

    second = run_migrations(settings)
    assert second["backup"] and Path(second["backup"]).exists()


def test_migrations_keep_existing_data(tmp_path):
    settings = Settings(data_dir=str(tmp_path), role="hub",
                        database_url=f"sqlite:///{tmp_path}/hub.db",
                        secret_key="migration-test-secret")
    run_migrations(settings)
    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO owners (id, username, password_hash, display_name, "
                          "is_active, created_at, updated_at) VALUES "
                          "('o1','owner','x','Owner',1,'2026-01-01','2026-01-01')"))
    run_migrations(settings)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM owners")).scalar() == 1


def test_core_entrypoint_intact():
    import main  # noqa: F401  — точка входа Core должна импортироваться

    assert callable(main.main)


def test_core_router_still_works():
    from core import ai_router

    answer = ai_router.route("состояние системы")
    assert isinstance(answer, str) and answer


def test_core_modules_unmodified():
    """В Core не должно быть изменений — экосистема строится поверх."""
    if not (ROOT / ".git").exists():
        pytest.skip("git недоступен")
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", "core", "ai", "interface", "voice",
         "config.py", "main.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.skip("git diff недоступен")
    assert result.stdout.strip() == "", f"Core изменён: {result.stdout}"


def test_bridge_reports_core_version():
    from ecosystem.backend.services import core_bridge

    assert core_bridge.core_available() is True
    assert core_bridge.core_version().startswith("v")
    assert core_bridge.core_build() in ("standard", "gov")


def test_bridge_blocks_side_effect_commands():
    from ecosystem.backend.services import core_bridge

    assert core_bridge.core_local_route("открой браузер") is None
    assert core_bridge.core_local_route("состояние системы") is not None


def test_restart_with_same_database_keeps_data(harness):
    harness.client.post("/api/tasks", headers=harness.headers, json={"title": "Пережить рестарт"})
    harness.make_app()
    login = harness.client.post("/api/auth/login",
                                json={"username": "owner", "password": "Sup3rSecret!"})
    assert login.status_code == 200
    harness.token = login.json()["token"]
    tasks = harness.client.get("/api/tasks", headers=harness.headers).json()["tasks"]
    assert [t["title"] for t in tasks] == ["Пережить рестарт"]


def test_health_endpoint_reports_role_and_core(hub):
    data = hub.client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["role"] == "hub"
    assert data["version"].startswith("2.0")


def test_audit_log_records_device_actions(hub):
    device = hub.client.post("/api/devices", headers=hub.headers,
                             json={"name": "AuditPC", "kind": "gpu"}).json()
    hub.client.post(f"/api/devices/{device['device']['id']}/commands", headers=hub.headers,
                    json={"action": "shell", "params": {}})
    device2 = hub.client.post("/api/devices", headers=hub.headers,
                              json={"name": "AuditPC2", "kind": "gpu"}).json()
    hub.client.post(f"/api/devices/{device2['device']['id']}/commands", headers=hub.headers,
                    json={"action": "sleep"})
    entries = hub.client.get("/api/audit", headers=hub.headers).json()["entries"]
    actions = [e["action"] for e in entries]
    assert "device.command" in actions
    assert "device.register" in actions
