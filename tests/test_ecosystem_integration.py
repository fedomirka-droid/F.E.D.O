"""Интеграционные проверки: Student Edition, привязка устройств, replay, снуз, AI health.

Здесь проверяется именно ИНТЕГРАЦИЯ, а не отдельные функции:
  * профиль студента синхронизируется и не дублируется на двух устройствах;
  * импортёр Student Edition работает на реальной SQLite (синтетической,
    потому что исходники MVP в репозитории отсутствуют) и идемпотентен;
  * без исходников `/api/student/import` честно отвечает 409, а не «успехом»;
  * привязка нового устройства по одноразовому коду (TTL, одно использование);
  * команда исполняется один раз и не принимается после истечения срока;
  * «отложить на 15 минут» двигает дедлайн и напоминание;
  * AI health возвращает состояние провайдеров без утечки ключей.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import uuid
from datetime import timedelta

import httpx
import pytest

from ecosystem.backend.db import utcnow
from ecosystem.backend.services import student


# --------------------------------------------------------------------------- #
# Student Edition
# --------------------------------------------------------------------------- #
def test_profile_is_created_once_and_has_deterministic_id(harness):
    first = harness.client.get("/api/student/profile", headers=harness.headers).json()
    second = harness.client.get("/api/student/profile", headers=harness.headers).json()
    assert first["id"] == second["id"] == student.profile_id(harness.owner_id)
    assert first["group_name"] == "ИС-21"

    updated = harness.client.put("/api/student/profile", headers=harness.headers,
                                 json={"specialty": "Информационные системы",
                                       "course": 3, "semester": 5,
                                       "college": "Колледж связи"}).json()
    assert updated["specialty"] == "Информационные системы"
    assert updated["course"] == 3 and updated["semester"] == 5
    assert updated["version"] >= 2


def test_profile_change_goes_to_outbox(harness):
    """Правка профиля обязана попасть в очередь синхронизации (а не только в БД)."""
    harness.client.put("/api/student/profile", headers=harness.headers,
                       json={"group_name": "ИС-21", "student_card": "21-ИС-042"})
    with harness.db.session() as db:
        from ecosystem.backend.models import StudentProfile
        from sqlalchemy import select

        rows = db.execute(select(StudentProfile)).scalars().all()
        outbox = harness.client.get("/api/sync/outbox", headers=harness.headers).json()["outbox"]
    assert len(rows) == 1, "профиль должен быть один на владельца"
    assert student.profile_id(harness.owner_id) == rows[0].id
    assert any(item["entity"] == "student_profile" for item in outbox), outbox


def test_profile_reaches_hub_through_sync(harness):
    """Полный путь: правка профиля на Desktop → push → профиль на HUB."""
    harness.client.put("/api/student/profile", headers=harness.headers,
                       json={"group_name": "ИС-21", "course": 3, "student_card": "21-ИС-042"})
    harness.settings.hub_url = "https://hub.example.invalid"
    harness.settings.sync_device_token = "dev_fake_token"
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sync/push":
            operations = json.loads(request.content)["operations"]
            captured["ops"] = operations
            return httpx.Response(200, json={"results": [{
                "status": "applied", "op_id": op["op_id"], "entity_id": op["entity_id"],
                "version": 2, "updated_at": "2026-10-29T17:00:00Z"} for op in operations]})
        return httpx.Response(200, json={"cursor": 1, "changes": []})

    import json as _json

    from ecosystem.backend.services import sync_worker

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    with harness.db.session() as db:
        result = sync_worker.run_sync(db, harness.settings, harness.owner_id, client=client)
    assert result["ok"] is True
    profile_ops = [op for op in captured["ops"] if op["entity"] == "student_profile"]
    assert profile_ops, captured["ops"]
    payload = profile_ops[0]["payload"]
    assert payload["course"] == 3
    assert payload["student_card"] == "21-ИС-042"


def _make_legacy_db(path):
    """Синтетическая база «Student Edition» с другой схемой колонок."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE tasks (id INTEGER PRIMARY KEY, name TEXT, notes TEXT,
                            prio TEXT, state TEXT, deadline TEXT, estimate INTEGER,
                            spent INTEGER, tag TEXT);
        CREATE TABLE lessons (id INTEGER PRIMARY KEY, lesson_date TEXT, pair INTEGER,
                              start TEXT, end TEXT, discipline TEXT, professor TEXT,
                              cabinet TEXT, type TEXT);
        CREATE TABLE student_profile (record_book TEXT, group_code TEXT, year INTEGER);
        INSERT INTO users (username) VALUES ('owner');
        INSERT INTO tasks (name, notes, prio, state, deadline, estimate, spent, tag)
            VALUES ('Лаба по сетям', 'Глава 3', 'high', 'doing', '2026-11-02', 60, 25, 'учёба'),
                   ('Реферат', '', 'normal', 'done', '2026-11-05', 90, 90, 'учёба'),
                   ('Лаба по сетям', 'Глава 3', 'high', 'doing', '2026-11-02', 60, 25, 'учёба');
        INSERT INTO lessons (lesson_date, pair, start, end, discipline, professor, cabinet, type)
            VALUES ('2026-10-30', 1, '09:00', '10:30', 'Сети', 'Иванов', '204', 'лекция'),
                   ('2026-10-30', 2, '10:40', '12:10', 'Базы данных', 'Петрова', '301', 'практика');
        INSERT INTO student_profile (record_book, group_code, year)
            VALUES ('21-ИС-042', 'ИС-21', 3);
    """)
    conn.commit()
    conn.close()


def test_detect_reports_blocked_without_sources(harness, tmp_path):
    status = harness.client.get("/api/student/status", headers=harness.headers).json()
    assert status["state"] in ("blocked", "adapter_ready")
    assert "missing" in status and status["missing"], "ожидался список недостающего"
    # Ключевой инвариант: если исходников нет, статус обязан быть blocked.
    if not status["found"] and not status["databases"]:
        assert status["integration"] == "blocked"


def test_import_refuses_without_sources(harness):
    resp = harness.client.post("/api/student/import", headers=harness.headers, json={})
    # либо 409 (исходников нет), либо 200 если в окружении реально что-то нашлось
    assert resp.status_code in (200, 409)
    if resp.status_code == 409:
        assert "отсутств" in resp.json()["detail"].lower()


def test_import_legacy_is_idempotent_and_maps_fields(harness, tmp_path):
    legacy = tmp_path / "student_edition.db"
    _make_legacy_db(legacy)

    first = harness.client.post("/api/student/import", headers=harness.headers,
                                json={"path": str(legacy)}).json()
    assert first["ok"] is True
    # дубль строки в legacy не должен дать две задачи
    assert first["tasks"]["created"] == 2
    assert first["schedule"]["created"] == 2
    assert first["users"]["matched"] == 1

    tasks = harness.client.get("/api/tasks", headers=harness.headers).json()["tasks"]
    assert len(tasks) == 2
    lab = next(t for t in tasks if t["title"] == "Лаба по сетям")
    assert lab["status"] == "in_progress" and lab["priority"] == "high"
    assert lab["planned_minutes"] == 60 and lab["actual_minutes"] == 25
    assert lab["due_at"].startswith("2026-11-02")

    schedule = harness.client.get("/api/schedule", headers=harness.headers).json()
    entries = schedule["entries"] if isinstance(schedule, dict) else schedule
    assert {e["subject"] for e in entries} == {"Сети", "Базы данных"}

    profile = harness.client.get("/api/student/profile", headers=harness.headers).json()
    assert profile["student_card"] == "21-ИС-042" and profile["course"] == 3
    assert profile["source"] == "legacy_import"

    # повторный импорт ничего не дублирует
    again = harness.client.post("/api/student/import", headers=harness.headers,
                                json={"path": str(legacy)}).json()
    assert again["tasks"]["created"] == 0
    assert again["schedule"]["created"] == 0
    assert len(harness.client.get("/api/tasks", headers=harness.headers).json()["tasks"]) == 2


def test_import_dry_run_writes_nothing(harness, tmp_path):
    legacy = tmp_path / "se.db"
    _make_legacy_db(legacy)
    report = harness.client.post("/api/student/import", headers=harness.headers,
                                 json={"path": str(legacy), "dry_run": True}).json()
    assert report["tasks"]["created"] == 2  # «что было бы создано»
    assert harness.client.get("/api/tasks", headers=harness.headers).json()["tasks"] == []


def test_import_rejects_non_sqlite_path(harness, tmp_path):
    bogus = tmp_path / "notes.txt"
    bogus.write_text("не база")
    resp = harness.client.post("/api/student/import", headers=harness.headers,
                               json={"path": str(bogus)})
    assert resp.status_code == 400
    assert "sqlite" in resp.json()["detail"].lower()


def test_detect_ignores_ecosystem_database(harness):
    """Своя база Ecosystem не должна считаться legacy-базой Student Edition."""
    detection = student.detect_legacy(roots=[pathlib.Path(harness.settings.data_dir)])
    assert detection["databases"] == [], detection["databases"]
    assert detection["state"] == "blocked"


def test_import_refuses_ecosystem_database(harness):
    """Импорт собственной базы запрещён: иначе пользователь получит дубли задач."""
    # Копия через backup API: WAL-файл может содержать схему, простой cp её потеряет
    real = pathlib.Path(harness.settings.database_url.replace("sqlite:///", ""))
    own_db = pathlib.Path(harness.settings.data_dir) / "copy-of-ecosystem.db"
    source = sqlite3.connect(real)
    target = sqlite3.connect(own_db)
    with target:
        source.backup(target)
    source.close()
    target.close()
    resp = harness.client.post("/api/student/import", headers=harness.headers,
                               json={"path": str(own_db)})
    assert resp.status_code == 400
    assert "Ecosystem" in resp.json()["detail"]


def test_detect_finds_database_when_sources_appear(tmp_path):
    _make_legacy_db(tmp_path / "F.E.D.O-Student-Edition.db")
    detection = student.detect_legacy(roots=[tmp_path])
    assert detection["state"] == "adapter_ready"
    assert detection["databases"], detection
    assert set(detection["databases"][0]["legacy_tables"]) >= {"tasks", "lessons"}
    assert detection["databases"][0]["signature_tables"], "нужен признак студенческой базы"


# --------------------------------------------------------------------------- #
# Привязка устройства по одноразовому коду
# --------------------------------------------------------------------------- #
def test_pairing_code_creates_device_once(hub):
    code = hub.client.post("/api/devices/pairing-code", headers=hub.headers,
                           json={"device_name": "ThinkPad", "device_kind": "desktop",
                                 "ttl_minutes": 5}).json()
    assert "-" in code["code"] and code["expires_at"]

    paired = hub.client.post("/api/devices/pair", json={
        "code": code["code"], "name": "ThinkPad", "kind": "desktop",
        "platform": "Windows 11"}).json()
    assert paired["token"].startswith("dev_") and paired["channel_secret"]
    assert paired["device"]["paired_at"]

    # токен рабочий
    hb = hub.client.post("/api/agent/heartbeat", headers={"X-Device-Token": paired["token"]},
                         json={"status": "online", "metrics": {"cpu_percent": 10}})
    assert hb.status_code == 200

    # второй раз тот же код не работает
    repeat = hub.client.post("/api/devices/pair", json={"code": code["code"],
                                                        "name": "HomePC", "kind": "gpu"})
    assert repeat.status_code == 400


def test_pairing_rejects_bad_and_expired_codes(hub):
    bad = hub.client.post("/api/devices/pair", json={"code": "AAAA-BBBB", "name": "X"})
    assert bad.status_code == 400

    code = hub.client.post("/api/devices/pairing-code", headers=hub.headers,
                           json={"ttl_minutes": 1}).json()
    from ecosystem.backend.models import PairingCode
    from ecosystem.backend.security import token_hash

    with hub.db.session() as db:
        record = db.execute(
            __import__("sqlalchemy").select(PairingCode).where(
                PairingCode.code_hash == token_hash(code["code"]))).scalar_one()
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.flush()
    expired = hub.client.post("/api/devices/pair", json={"code": code["code"], "name": "X"})
    assert expired.status_code == 400
    assert "истёк" in expired.json()["detail"].lower()


def test_pairing_code_hash_is_not_stored_plain(hub):
    from ecosystem.backend.models import PairingCode

    code = hub.client.post("/api/devices/pairing-code", headers=hub.headers, json={}).json()
    with hub.db.session() as db:
        row = db.execute(__import__("sqlalchemy").select(PairingCode)).scalars().first()
    assert row.code_hash != code["code"]
    assert len(row.code_hash) == 64


# --------------------------------------------------------------------------- #
# Выполнение команд: одноразовость, срок, белый список приложений
# --------------------------------------------------------------------------- #
def _device(hub, **extra):
    payload = {"name": "HomePC", "kind": "gpu", "capabilities": ["ai"]}
    payload.update(extra)
    resp = hub.client.post("/api/devices", headers=hub.headers, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_command_is_delivered_once(hub):
    device = _device(hub)
    token = {"X-Device-Token": device["token"]}
    hub.client.post(f"/api/devices/{device['device']['id']}/commands",
                    headers=hub.headers, json={"action": "status"})
    first = hub.client.get("/api/agent/poll", headers=token).json()["commands"]
    assert len(first) == 1
    second = hub.client.get("/api/agent/poll", headers=token).json()["commands"]
    assert second == [], "команда не должна выдаваться повторно"


def test_expired_command_is_never_delivered(hub):
    device = _device(hub)
    token = {"X-Device-Token": device["token"]}
    cmd = hub.client.post(f"/api/devices/{device['device']['id']}/commands",
                          headers=hub.headers, json={"action": "status"}).json()
    from ecosystem.backend.models import DeviceCommand

    with hub.db.session() as db:
        record = db.get(DeviceCommand, cmd["id"])
        record.expires_at = utcnow() - timedelta(seconds=5)
        db.flush()
    poll = hub.client.get("/api/agent/poll", headers=token).json()["commands"]
    assert poll == []
    history = hub.client.get(f"/api/devices/{device['device']['id']}/commands",
                             headers=hub.headers).json()["commands"]
    assert history[0]["status"] == "expired"


def test_new_actions_are_dangerous_and_catalogued(hub):
    device = _device(hub)
    catalog = {a["action"]: a for a in
               hub.client.get("/api/devices", headers=hub.headers).json()["actions"]}
    for action in ("lock", "shutdown", "launch", "stop_app", "sleep", "wol",
                   "stats", "ai_check", "status"):
        assert action in catalog, f"{action} отсутствует в каталоге"
    assert catalog["status"]["dangerous"] is False
    hub.client.patch(f"/api/devices/{device['device']['id']}", headers=hub.headers,
                     json={"command_allowlist": [
                         {"label": "Блокнот", "command": "C:/Windows/notepad.exe"}]})
    for action in ("lock", "shutdown", "launch", "stop_app", "sleep", "wol"):
        assert catalog[action]["dangerous"] is True
        params = {"app": "Блокнот"} if action in ("launch", "stop_app") else {}
        resp = hub.client.post(f"/api/devices/{device['device']['id']}/commands",
                               headers=hub.headers, json={"action": action, "params": params})
        assert resp.status_code == 200, (action, resp.text)
        assert resp.json()["requires_confirmation"] is True


def test_launch_requires_app_in_device_allowlist(hub):
    device = _device(hub)
    device_id = device["device"]["id"]

    denied = hub.client.post(f"/api/devices/{device_id}/commands", headers=hub.headers,
                             json={"action": "launch", "params": {"app": "notepad.exe"}})
    assert denied.status_code == 400
    assert "не разрешено" in denied.json()["detail"].lower()

    patched = hub.client.patch(f"/api/devices/{device_id}", headers=hub.headers,
                               json={"command_allowlist": [
                                   {"label": "Блокнот", "command": "C:/Windows/notepad.exe"}]})
    assert patched.status_code == 200
    assert patched.json()["command_allowlist"][0]["command"].endswith("notepad.exe")

    allowed = hub.client.post(f"/api/devices/{device_id}/commands", headers=hub.headers,
                              json={"action": "launch", "params": {"app": "Блокнот"}}).json()
    assert allowed["requires_confirmation"] is True
    assert allowed["params"]["command"].endswith("notepad.exe")


def test_allowlist_rejects_shell_constructs(hub):
    device = _device(hub)
    resp = hub.client.patch(f"/api/devices/{device['device']['id']}", headers=hub.headers,
                            json={"command_allowlist": [
                                {"label": "плохо", "command": "cmd.exe /c del /q *"}]})
    assert resp.status_code == 400


def test_agent_denies_action_outside_its_own_allowlist():
    from ecosystem.agent.runtime import AgentExecutor, AgentPolicy

    executor = AgentExecutor(AgentPolicy(simulate=True, allow_apps=True,
                                         apps={"Блокнот": ["C:/Windows/notepad.exe"]}))
    ok = executor.execute("launch", {"app": "Блокнот"})
    assert ok["ok"] is True and ok["simulated"] is True

    denied = executor.execute("launch", {"app": "Калькулятор"})
    assert denied["ok"] is False and denied["denied"] is True

    # даже подсказка с чужим путём не выполняется
    denied_hint = executor.execute("launch", {"app": "Калькулятор",
                                              "command": "C:/Windows/calc.exe"})
    assert denied_hint["ok"] is False and denied_hint["denied"] is True


def test_agent_requires_explicit_permission_for_lock_and_shutdown():
    from ecosystem.agent.runtime import AgentExecutor, AgentPolicy

    executor = AgentExecutor(AgentPolicy(simulate=True))
    assert executor.execute("lock", {})["denied"] is True
    assert executor.execute("shutdown", {})["denied"] is True

    allowed = AgentExecutor(AgentPolicy(simulate=True, allow_lock=True, allow_power=True))
    assert allowed.execute("lock", {})["ok"] is True
    shutdown = allowed.execute("shutdown", {"delay": "30"})
    assert shutdown["ok"] is True and shutdown["delay"] == 30


# --------------------------------------------------------------------------- #
# Задачи: «отложить на 15 минут»
# --------------------------------------------------------------------------- #
def test_snooze_shifts_deadline_and_reminder(harness):
    due = utcnow() + timedelta(hours=1)
    task = harness.client.post("/api/tasks", headers=harness.headers, json={
        "title": "Позвонить", "due_at": due.isoformat() + "Z",
        "remind_at": due.isoformat() + "Z"}).json()
    snoozed = harness.client.post(
        f"/api/tasks/{task['id']}/action/snooze?minutes=15", headers=harness.headers).json()
    assert snoozed["due_at"] and snoozed["remind_at"]
    from datetime import datetime

    new_due = datetime.fromisoformat(snoozed["due_at"].replace("Z", "+00:00"))
    delta = (new_due - due.replace(tzinfo=new_due.tzinfo)).total_seconds() / 60
    assert 14 <= delta <= 16
    assert snoozed["planned_minutes"] == task["planned_minutes"]


# --------------------------------------------------------------------------- #
# AI Router: health
# --------------------------------------------------------------------------- #
def test_ai_health_reports_local_only_safely(harness, no_network, monkeypatch):
    from ecosystem.backend.providers import local_lmstudio

    async def no_models(self):
        raise local_lmstudio.ProviderError("LM Studio недоступен")

    monkeypatch.setattr(local_lmstudio.LocalLMStudioProvider, "list_models", no_models)

    harness.client.put("/api/ai/settings", headers=harness.headers,
                       json={"mode": "local_only", "allow_cloud": False})
    health = harness.client.get("/api/ai/health", headers=harness.headers).json()
    assert health["mode"] == "local_only"
    assert health["local"]["available"] is False
    assert health["cloud"]["usable"] is False
    assert health["privacy"] == "local_only_enforced"
    assert "api_key" not in str(health).lower()
    assert health["fallback_plan"], "должен быть описан план fallback"


def test_ai_health_shows_cloud_only_when_allowed(harness):
    harness.client.post("/api/ai/keys/gemini", headers=harness.headers,
                        json={"api_key": "test-key-not-real"})
    harness.client.put("/api/ai/settings", headers=harness.headers,
                       json={"mode": "hybrid", "allow_cloud": True})
    health = harness.client.get("/api/ai/health", headers=harness.headers).json()
    assert health["cloud"]["key_configured"] is True
    assert health["cloud"]["allowed"] is True
    assert "test-key-not-real" not in str(health)


def test_chat_text_cannot_trigger_system_actions(harness, monkeypatch):
    """Ключевая проверка безопасности: текст не превращается в действия ПК."""
    from ecosystem.backend.services import core_bridge

    called = {"browser": 0, "log": 0}

    monkeypatch.setattr(core_bridge, "core_local_route", core_bridge.core_local_route)
    import core.commands as core_commands

    monkeypatch.setattr(core_commands, "open_site",
                        lambda *a, **k: called.__setitem__("browser", called["browser"] + 1) or "browser")
    monkeypatch.setattr(core_commands, "clear_log",
                        lambda *a, **k: called.__setitem__("log", called["log"] + 1) or "log")

    for text in ("найди погода в лондоне", "очисти лог", "покажи лог",
                 "открой браузер", "открой путь C:/Windows"):
        assert core_bridge.core_local_route(text) is None, text
    assert called == {"browser": 0, "log": 0}
    # а безопасные команды по-прежнему работают
    assert core_bridge.core_local_route("время")


# --------------------------------------------------------------------------- #
# Ручное занятие в расписании (без Excel)
# --------------------------------------------------------------------------- #
def test_manual_lesson_create_update_and_sync(harness):
    client, auth = harness.client, harness.headers
    created = client.post("/api/schedule", headers=auth, json={
        "date": "2026-11-02", "subject": "Философия", "start_time": "12:20",
        "end_time": "13:50", "teacher": "Орлова М.В.", "room": "каб. 118",
        "group_name": "ИС-21"})
    assert created.status_code == 200, created.text
    lesson = created.json()
    assert lesson["subject"] == "Философия"
    assert lesson["slot"] == 3          # 12:20 — третья пара

    day = client.get("/api/schedule", headers=auth, params={"day": "2026-11-02"}).json()
    assert [e["subject"] for e in day["entries"]] == ["Философия"]

    patched = client.patch(f"/api/schedule/{lesson['id']}", headers=auth, json={
        "date": "2026-11-02", "subject": "Философия", "start_time": "12:20",
        "teacher": "Орлова М.В.", "room": "ауд. 205", "group_name": "ИС-21"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["room"] == "ауд. 205"


def test_manual_lesson_rejects_bad_date_and_time(harness):
    client, auth = harness.client, harness.headers
    bad_date = client.post("/api/schedule", headers=auth, json={
        "date": "02.11.2026", "subject": "История"})
    assert bad_date.status_code == 422
    bad_time = client.post("/api/schedule", headers=auth, json={
        "date": "2026-11-03", "subject": "История", "start_time": "25:99"})
    assert bad_time.status_code == 422
    empty_subject = client.post("/api/schedule", headers=auth, json={
        "date": "2026-11-03", "subject": ""})
    assert empty_subject.status_code == 422


# --------------------------------------------------------------------------- #
# Резервная копия базы
# --------------------------------------------------------------------------- #
def test_backup_creates_consistent_copy(harness):
    harness.client.post("/api/tasks", headers=harness.headers,
                        json={"title": "Перед бэкапом", "priority": "high"})
    made = harness.client.post("/api/system/backup", headers=harness.headers)
    assert made.status_code == 200, made.text
    payload = made.json()
    assert payload["ok"] and payload["size"] > 0 and len(payload["checksum"]) == 64

    copy = pathlib.Path(payload["path"])
    assert copy.is_file()
    con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in con.execute(
            "select name from sqlite_master where type='table'").fetchall()}
        titles = [row[0] for row in con.execute("select title from tasks").fetchall()]
    finally:
        con.close()
    assert {"owners", "tasks", "outbox"} <= tables
    assert "Перед бэкапом" in titles

    listed = harness.client.get("/api/system/backups", headers=harness.headers).json()
    assert any(item["name"] == copy.name for item in listed["backups"])


def test_backup_requires_auth_and_info_hides_secrets(harness):
    assert harness.client.post("/api/system/backup").status_code == 401
    info = harness.client.get("/api/system/info", headers=harness.headers).json()
    assert info["version"] and "data_dir" in info
    assert not any("token" in key.lower() and "configured" not in key.lower()
                   for key in info), info
