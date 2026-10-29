"""Проверки 5–7, 20: синхронизация, дубли, конфликты, офлайн-очередь, перезапуск."""
from __future__ import annotations

import json

import httpx

from ecosystem.backend.services import sync_engine, sync_worker


def _device(hub, name: str = "ThinkPad") -> dict:
    resp = hub.client.post("/api/devices", headers=hub.headers,
                           json={"name": name, "kind": "desktop",
                                 "capabilities": ["ai", "montitor"]})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _op(op_id: str, entity_id: str, title: str, base_version: int = 0,
        operation: str = "upsert") -> dict:
    return {"op_id": op_id, "entity": "task", "entity_id": entity_id,
            "operation": operation, "base_version": base_version,
            "payload": {"title": title, "description": "", "priority": "normal",
                        "status": "todo", "planned_minutes": 30, "actual_minutes": 0}}


def test_push_pull_and_isolation(hub):
    dev_a = _device(hub, "ThinkPad")
    dev_b = _device(hub, "HomePC")
    task_id = "11111111-1111-1111-1111-111111111111"

    first = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_a["token"]},
                            json={"operations": [_op("op-aaaaaa1", task_id, "Лаба")]})
    assert first.status_code == 200
    result = first.json()["results"][0]
    assert result["status"] == "applied" and result["version"] == 1

    repeat = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_a["token"]},
                             json={"operations": [_op("op-aaaaaa1", task_id, "Лаба")]})
    assert repeat.json()["results"][0]["idempotent"] is True
    assert repeat.json()["results"][0]["version"] == 1

    own = hub.client.get("/api/sync/pull", headers={"X-Device-Token": dev_a["token"]},
                         params={"cursor": 0, "exclude_device": dev_a["device"]["id"]}).json()
    assert own["changes"] == []

    other = hub.client.get("/api/sync/pull", headers={"X-Device-Token": dev_b["token"]},
                           params={"cursor": 0}).json()
    assert other["count"] == 1
    assert other["changes"][0]["payload"]["title"] == "Лаба"
    cursor = other["cursor"]

    again = hub.client.get("/api/sync/pull", headers={"X-Device-Token": dev_b["token"]},
                           params={"cursor": cursor}).json()
    assert again["changes"] == [] and again["cursor"] == cursor


def test_stale_version_creates_conflict_and_keeps_both(hub):
    dev_a = _device(hub, "ThinkPad")
    dev_b = _device(hub, "HomePC")
    task_id = "22222222-2222-2222-2222-222222222222"

    hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_a["token"]},
                    json={"operations": [_op("op-bbbbbb1", task_id, "Исходная")]})
    hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_a["token"]},
                    json={"operations": [_op("op-bbbbbb2", task_id, "Правка A", base_version=1)]})

    stale = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_b["token"]},
                            json={"operations": [_op("op-cccccc1", task_id, "Правка B", base_version=1)]})
    conflict = stale.json()["results"][0]
    assert conflict["status"] == "conflict"
    assert conflict["server"]["title"] == "Правка A"
    assert conflict["server_version"] == 2

    task = hub.client.get(f"/api/tasks/{task_id}", headers=hub.headers).json()
    assert task["title"] == "Правка A"  # сервер не перезаписан

    conflicts = hub.client.get("/api/sync/conflicts", headers=hub.headers).json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["incoming"]["title"] == "Правка B"

    resolved = hub.client.post(f"/api/sync/conflicts/{conflicts[0]['id']}/resolve",
                               headers=hub.headers, json={"resolution": "local"})
    assert resolved.status_code == 200 and resolved.json()["ok"] is True
    task = hub.client.get(f"/api/tasks/{task_id}", headers=hub.headers).json()
    assert task["title"] == "Правка B" and task["version"] == 3

    open_conflicts = hub.client.get("/api/sync/conflicts", headers=hub.headers).json()["conflicts"]
    assert open_conflicts == []


def test_conflict_can_keep_server_version(hub):
    dev_a = _device(hub, "ThinkPad")
    task_id = "33333333-3333-3333-3333-333333333333"
    hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_a["token"]},
                    json={"operations": [_op("op-dddddd1", task_id, "Сервер")]})
    conflict = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_a["token"]},
                               json={"operations": [_op("op-dddddd2", task_id, "Другое", base_version=0)]}
                               ).json()["results"][0]
    hub.client.post(f"/api/sync/conflicts/{conflict['conflict_id']}/resolve",
                    headers=hub.headers, json={"resolution": "server"})
    task = hub.client.get(f"/api/tasks/{task_id}", headers=hub.headers).json()
    assert task["title"] == "Сервер"


def test_duplicate_content_does_not_bump_version(hub):
    dev = _device(hub)
    task_id = "44444444-4444-4444-4444-444444444444"
    hub.client.post("/api/sync/push", headers={"X-Device-Token": dev["token"]},
                    json={"operations": [_op("op-eeeeee1", task_id, "Одна и та же")]})
    second = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev["token"]},
                             json={"operations": [_op("op-eeeeee2", task_id, "Одна и та же", base_version=1)]})
    assert second.json()["results"][0].get("duplicate") is True
    task = hub.client.get(f"/api/tasks/{task_id}", headers=hub.headers).json()
    assert task["version"] == 1


def test_local_outbox_survives_restart_and_backoff(harness, monkeypatch):
    harness.client.post("/api/tasks", headers=harness.headers, json={"title": "Офлайн-задача"})
    harness.settings.hub_url = "https://hub.example.invalid"
    harness.settings.sync_device_token = "dev_fake_token"

    def failing_client(timeout=None):
        def handler(request: httpx.Request):
            raise httpx.ConnectError("hub unreachable", request=request)
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    with harness.db.session() as db:
        result = sync_worker.run_sync(db, harness.settings, harness.owner_id,
                                      client=failing_client())
    assert result["ok"] is False
    status = harness.client.get("/api/sync/status", headers=harness.headers).json()
    assert status["pending_operations"] == 1
    assert status["last_error"]

    # «перезапуск приложения» — очередь не потерялась
    harness.make_app()
    harness.token = harness.client.post("/api/auth/login",
                                        json={"username": "owner", "password": "Sup3rSecret!"}
                                        ).json()["token"]
    outbox = harness.client.get("/api/sync/outbox", headers=harness.headers).json()["outbox"]
    assert len(outbox) == 1
    assert outbox[0]["attempts"] >= 1
    assert outbox[0]["next_attempt_at"] is not None


def test_successful_sync_drains_queue_and_applies_remote(harness):
    task = harness.client.post("/api/tasks", headers=harness.headers,
                               json={"title": "Локальная"}).json()
    harness.settings.hub_url = "https://hub.example.invalid"
    harness.settings.sync_device_token = "dev_fake_token"

    remote_id = "55555555-5555-5555-5555-555555555555"
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/sync/push":
            op = __import__("json").loads(request.content)["operations"][0]
            return httpx.Response(200, json={"results": [{
                "status": "applied", "op_id": op["op_id"], "entity_id": op["entity_id"],
                "version": 1, "updated_at": "2026-10-29T10:00:00Z"}]})
        if request.url.path == "/api/sync/pull":
            return httpx.Response(200, json={"cursor": 7, "count": 1, "changes": [{
                "cursor": 7, "entity": "task", "entity_id": remote_id, "version": 1,
                "operation": "upsert", "device_id": "other-device",
                "payload": {"title": "С домашнего ПК", "priority": "high", "status": "todo",
                            "updated_at": "2026-10-29T11:00:00Z"}}]})
        raise AssertionError(request.url.path)

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    with harness.db.session() as db:
        result = sync_worker.run_sync(db, harness.settings, harness.owner_id, client=client)
    assert result["ok"] is True
    assert result["applied"] == 1 and result["pulled"] == 1

    status = harness.client.get("/api/sync/status", headers=harness.headers).json()
    assert status["pending_operations"] == 0
    assert status["cursor"] == 7 and status["online"] is True

    tasks = harness.client.get("/api/tasks", headers=harness.headers).json()["tasks"]
    titles = {t["title"] for t in tasks}
    assert {"Локальная", "С домашнего ПК"} <= titles
    assert calls.count("/api/sync/push") == 1 and calls.count("/api/sync/pull") == 1


def test_pull_does_not_duplicate_rows(harness):
    with harness.db.session() as db:
        change = {
            "cursor": 1, "entity": "task", "entity_id": "66666666-6666-6666-6666-666666666666",
            "version": 1, "operation": "upsert", "device_id": "dev-x",
            "payload": {"title": "Изменение", "priority": "normal", "status": "todo",
                        "updated_at": "2026-10-29T12:00:00Z"},
        }
        assert sync_engine.apply_remote_change(db, harness.owner_id, change) == "applied"
        assert sync_engine.apply_remote_change(db, harness.owner_id, change) == "skipped"
    tasks = harness.client.get("/api/tasks", headers=harness.headers).json()["tasks"]
    assert len(tasks) == 1


def test_pending_local_edit_creates_conflict_not_overwrite(harness):
    task = harness.client.post("/api/tasks", headers=harness.headers,
                               json={"title": "Локально изменённая"}).json()
    with harness.db.session() as db:
        change = {
            "cursor": 2, "entity": "task", "entity_id": task["id"], "version": 5,
            "operation": "upsert", "device_id": "other",
            "payload": {"title": "С другого устройства", "updated_at": "2026-10-29T13:00:00Z"},
        }
        outcome = sync_engine.apply_remote_change(db, harness.owner_id, change)
    assert outcome == "conflict"
    current = harness.client.get(f"/api/tasks/{task['id']}", headers=harness.headers).json()
    assert current["title"] == "Локально изменённая"
    conflicts = harness.client.get("/api/sync/conflicts", headers=harness.headers).json()["conflicts"]
    assert len(conflicts) == 1


def test_sync_rejects_foreign_owner_entity(hub):
    from ecosystem.backend.models import Owner
    from ecosystem.backend.security import hash_password

    with hub.db.session() as db:
        other = Owner(username="other", password_hash=hash_password("OtherPass1!"))
        db.add(other)
        db.flush()
        other_id = other.id

    dev = _device(hub, "ThinkPad")
    task_id = "77777777-7777-7777-7777-777777777777"
    with hub.db.session() as db:
        from ecosystem.backend.models import Task

        db.add(Task(id=task_id, owner_id=other_id, title="чужая"))

    result = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev["token"]},
                             json={"operations": [_op("op-ffffff1", task_id, "Захват")]}).json()["results"][0]
    assert result["status"] == "rejected"
    task = hub.client.get(f"/api/tasks/{task_id}", headers=hub.headers)
    assert task.status_code == 404


def test_revoked_device_token_is_rejected(hub):
    dev = _device(hub, "Old")
    hub.client.post(f"/api/devices/{dev['device']['id']}/revoke", headers=hub.headers)
    resp = hub.client.get("/api/sync/pull", headers={"X-Device-Token": dev["token"]})
    assert resp.status_code == 401


def test_backoff_grows():
    assert sync_worker and sync_engine.backoff_seconds(1) == 5
    assert sync_engine.backoff_seconds(3) == 20
    assert sync_engine.backoff_seconds(20) == 300


def test_client_resolves_conflict_locally_and_pushes_it_to_hub(harness):
    """Выбор «моя версия» на ноутбуке обязан уехать на HUB, а не остаться локально."""
    task = harness.client.post("/api/tasks", headers=harness.headers,
                               json={"title": "Правка на ноутбуке"}).json()
    harness.settings.hub_url = "https://hub.example.invalid"
    harness.settings.sync_device_token = "dev_fake_token"

    # имитируем конфликт, полученный при push на HUB
    with harness.db.session() as db:
        from ecosystem.backend.models import SyncConflict

        db.add(SyncConflict(
            id="conf-local-1", owner_id=harness.owner_id, entity="task",
            entity_id=task["id"], base_version=1, server_version=3,
            incoming={"title": "Правка на ноутбуке", "operation": "upsert",
                      "priority": "high"},
            server={"title": "Правка на HUB", "priority": "normal"}, device_id="dev-a",
        ))
        db.flush()

    resp = harness.client.post("/api/sync/conflicts/conf-local-1/resolve",
                               headers=harness.headers, json={"resolution": "local"})
    assert resp.status_code == 200 and resp.json()["ok"] is True

    outbox = harness.client.get("/api/sync/outbox", headers=harness.headers).json()["outbox"]
    assert len(outbox) == 1, outbox
    assert outbox[0]["operation"] == "upsert"
    assert outbox[0]["base_version"] == 3, "базовая версия должна совпадать с версией HUB"

    # push на HUB принимает операцию как обычный апдейт версии 3 -> 4
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sync/push":
            op = json.loads(request.content)["operations"][0]
            seen["op"] = op
            return httpx.Response(200, json={"results": [{
                "status": "applied", "op_id": op["op_id"], "entity_id": op["entity_id"],
                "version": 4, "updated_at": "2026-10-29T14:00:00Z"}]})
        if request.url.path == "/api/sync/pull":
            return httpx.Response(200, json={"cursor": 0, "count": 0, "changes": []})
        raise AssertionError(request.url.path)

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    with harness.db.session() as db:
        result = sync_worker.run_sync(db, harness.settings, harness.owner_id, client=client)
    assert result["ok"] is True and result["applied"] == 1
    assert seen["op"]["base_version"] == 3
    assert seen["op"]["payload"]["title"] == "Правка на ноутбуке"
    assert seen["op"]["payload"]["priority"] == "high"
    local = harness.client.get(f"/api/tasks/{task['id']}", headers=harness.headers).json()
    assert local["version"] == 4
    assert harness.client.get("/api/sync/outbox",
                              headers=harness.headers).json()["outbox"] == []


def test_hub_conflict_resolution_does_not_enqueue_outbox(hub):
    """На HUB outbox не нужен: он не синхронизируется сам с собой."""
    hub.client.post("/api/sync/push",
                    headers={"X-Device-Token": _device(hub)["token"]},
                    json={"operations": [_op("op-conf1", "77777777-7777-7777-7777-777777777777",
                                             "Версия 1")]})
    hub.client.post("/api/sync/push",
                    headers={"X-Device-Token": _device(hub, "HomePC")["token"]},
                    json={"operations": [_op("op-conf2", "77777777-7777-7777-7777-777777777777",
                                             "Версия 2", base_version=5)]})
    conflicts = hub.client.get("/api/sync/conflicts", headers=hub.headers).json()["conflicts"]
    assert conflicts, "ожидался конфликт версий"
    resp = hub.client.post(f"/api/sync/conflicts/{conflicts[0]['id']}/resolve",
                           headers=hub.headers, json={"resolution": "local"})
    assert resp.status_code == 200
    assert hub.client.get("/api/sync/outbox", headers=hub.headers).json()["outbox"] == []
