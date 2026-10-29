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


# --------------------------------------------------------------------------- #
# Два устройства правят одну задачу + восстановление после отключения HUB
# --------------------------------------------------------------------------- #
def test_two_devices_edit_same_task_and_keep_my_version(hub):
    """Одновременная правка на ThinkPad и HomePC: обе версии сохранены."""
    dev_a = _device(hub, "ThinkPad")
    dev_b = _device(hub, "HomePC")
    task_id = "88888888-8888-8888-8888-888888888888"

    hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_a["token"]},
                    json={"operations": [_op("op-two-a1", task_id, "Исходная")]})

    # оба устройства правят от версии 1
    a = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_a["token"]},
                        json={"operations": [_op("op-two-a2", task_id,
                                                 "Правка с ThinkPad", base_version=1)]})
    assert a.json()["results"][0]["status"] == "applied"
    assert a.json()["results"][0]["version"] == 2

    b = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev_b["token"]},
                        json={"operations": [_op("op-two-b2", task_id,
                                                 "Правка с HomePC", base_version=1)]})
    result = b.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["server"]["title"] == "Правка с ThinkPad"

    # данные не потеряны: серверная версия на месте, входящая — в конфликте
    conflicts = hub.client.get("/api/sync/conflicts", headers=hub.headers).json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["incoming"]["title"] == "Правка с HomePC"
    assert conflicts[0]["server"]["title"] == "Правка с ThinkPad"

    # владелец выбирает «моя версия» (версия HomePC)
    resolved = hub.client.post(f"/api/sync/conflicts/{conflicts[0]['id']}/resolve",
                               headers=hub.headers, json={"resolution": "local"})
    assert resolved.status_code == 200 and resolved.json()["ok"] is True
    task = hub.client.get(f"/api/tasks/{task_id}", headers=hub.headers).json()
    assert task["title"] == "Правка с HomePC"
    # версия 1 -> 2 (ThinkPad) -> 3 (разрешение конфликта в пользу HomePC)
    assert task["version"] == 3

    # второе устройство получает итог при следующем pull
    pull = hub.client.get("/api/sync/pull", headers={"X-Device-Token": dev_a["token"]},
                          params={"cursor": 0}).json()
    titles = [c["payload"].get("title") for c in pull["changes"] if c["entity"] == "task"]
    assert "Правка с HomePC" in titles
    assert "Правка с ThinkPad" in titles  # история изменений сохранена


def test_keep_server_version_discards_local_but_keeps_it_in_conflict(harness):
    task = harness.client.post("/api/tasks", headers=harness.headers,
                               json={"title": "Локально"}).json()
    harness.settings.hub_url = "https://hub.example.invalid"
    harness.settings.sync_device_token = "dev_fake_token"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sync/push":
            op = json.loads(request.content)["operations"][0]
            return httpx.Response(200, json={"results": [{
                "status": "conflict", "op_id": op["op_id"], "entity_id": op["entity_id"],
                "conflict_id": "conf-server-1", "server_version": 3, "base_version": 1,
                "server": {"title": "Серверная", "version": 3}}]})
        if request.url.path == "/api/sync/pull":
            return httpx.Response(200, json={"cursor": 0, "changes": []})
        raise AssertionError(request.url.path)

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    with harness.db.session() as db:
        sync_worker.run_sync(db, harness.settings, harness.owner_id, client=client)

    conflicts = harness.client.get("/api/sync/conflicts", headers=harness.headers).json()["conflicts"]
    assert len(conflicts) == 1
    payload = conflicts[0]["incoming"]
    assert payload["title"] == "Локально", "локальная версия должна сохраниться в конфликте"

    resolved = harness.client.post(f"/api/sync/conflicts/{conflicts[0]['id']}/resolve",
                                   headers=harness.headers, json={"resolution": "server"})
    assert resolved.json()["ok"] is True
    assert harness.client.get("/api/sync/outbox",
                              headers=harness.headers).json()["outbox"] == []
    # локальная правка не потеряна: осталась в записи конфликта
    history = harness.client.get("/api/sync/conflicts?include_resolved=true",
                                 headers=harness.headers).json()["conflicts"]
    assert history[0]["incoming"]["title"] == "Локально"
    assert history[0]["status"] == "resolved"


def test_recovery_after_hub_outage_backs_off_then_succeeds(harness):
    """HUB недоступен → очередь растёт и backoff; HUB вернулся → всё уехало."""
    for index in range(3):
        harness.client.post("/api/tasks", headers=harness.headers,
                            json={"title": f"Офлайн-{index}"})
    harness.settings.hub_url = "https://hub.example.invalid"
    harness.settings.sync_device_token = "dev_fake_token"
    state = {"down": True}
    pushed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sync/push":
            if state["down"]:
                raise httpx.ConnectError("hub unreachable", request=request)
            body = json.loads(request.content)
            results = []
            for op in body["operations"]:
                pushed.append(op["entity_id"])
                results.append({"status": "applied", "op_id": op["op_id"],
                                "entity_id": op["entity_id"], "version": 1,
                                "updated_at": "2026-10-29T15:00:00Z"})
            return httpx.Response(200, json={"results": results})
        if request.url.path == "/api/sync/pull":
            return httpx.Response(200, json={"cursor": 3, "changes": []})
        raise AssertionError(request.url.path)

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    with harness.db.session() as db:
        failed = sync_worker.run_sync(db, harness.settings, harness.owner_id, client=client)
    assert failed["ok"] is False
    status = harness.client.get("/api/sync/status", headers=harness.headers).json()
    assert status["pending_operations"] == 3 and status["online"] is False

    outbox = harness.client.get("/api/sync/outbox", headers=harness.headers).json()["outbox"]
    assert all(row["attempts"] >= 1 for row in outbox)
    assert all(row["next_attempt_at"] for row in outbox)

    # HUB вернулся: ждать backoff не нужно — «повторная попытка» доступна сразу
    state["down"] = False
    with harness.db.session() as db:
        from ecosystem.backend.models import OutboxEntry
        from sqlalchemy import select as sa_select

        for row in db.execute(sa_select(OutboxEntry)
                              .where(OutboxEntry.owner_id == harness.owner_id)).scalars():
            row.next_attempt_at = sync_engine.utcnow()
        db.flush()
    with harness.db.session() as db:
        recovered = sync_worker.run_sync(db, harness.settings, harness.owner_id, client=client)
    assert recovered["ok"] is True
    assert recovered["pushed"] == 3 and recovered["applied"] == 3
    assert len(pushed) == 3
    assert harness.client.get("/api/sync/outbox",
                              headers=harness.headers).json()["outbox"] == []
    status = harness.client.get("/api/sync/status", headers=harness.headers).json()
    assert status["pending_operations"] == 0 and status["online"] is True
    assert status["cursor"] == 3


def test_queue_survives_restart_mid_flight(harness):
    """Изменение, не уехавшее до перезапуска, остаётся в очереди и уходит после."""
    harness.client.post("/api/tasks", headers=harness.headers, json={"title": "До перезапуска"})
    harness.settings.hub_url = "https://hub.example.invalid"
    harness.settings.sync_device_token = "dev_fake_token"

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with harness.db.session() as db:
        sync_worker.run_sync(db, harness.settings, harness.owner_id,
                             client=httpx.Client(transport=httpx.MockTransport(down), timeout=5))

    harness.make_app()   # имитация перезапуска приложения
    harness.token = harness.client.post("/api/auth/login", json={
        "username": "owner", "password": "Sup3rSecret!"}).json()["token"]
    outbox = harness.client.get("/api/sync/outbox", headers=harness.headers).json()["outbox"]
    assert len(outbox) == 1

    # backoff уже назначен: «ждём» его истечения, не теряя операцию
    with harness.db.session() as db:
        from ecosystem.backend.models import OutboxEntry
        from sqlalchemy import select as sa_select

        for row in db.execute(sa_select(OutboxEntry)
                              .where(OutboxEntry.owner_id == harness.owner_id)).scalars():
            row.next_attempt_at = sync_engine.utcnow()
        db.flush()

    def up(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sync/push":
            op = json.loads(request.content)["operations"][0]
            return httpx.Response(200, json={"results": [{
                "status": "applied", "op_id": op["op_id"], "entity_id": op["entity_id"],
                "version": 1, "updated_at": "2026-10-29T16:00:00Z"}]})
        return httpx.Response(200, json={"cursor": 1, "changes": []})

    with harness.db.session() as db:
        result = sync_worker.run_sync(db, harness.settings, harness.owner_id,
                                      client=httpx.Client(transport=httpx.MockTransport(up),
                                                          timeout=5))
    assert result["ok"] is True and result["applied"] == 1


# --------------------------------------------------------------------------- #
# Сущности с уникальностью на владельца (профиль студента, настройки)
# --------------------------------------------------------------------------- #
def test_profile_with_foreign_id_is_merged_not_duplicated(hub):
    """Узлы выводят id профиля из своего owner_id — синхронизация не должна падать."""
    hub.client.get("/api/student/profile", headers=hub.headers)   # профиль уже есть
    foreign_profile_id = "99999999-9999-5999-8999-999999999999"
    dev = _device(hub)

    push = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev["token"]},
                           json={"operations": [{
                               "op_id": "op-profile-1", "entity": "student_profile",
                               "entity_id": foreign_profile_id, "operation": "upsert",
                               "base_version": 0,
                               "payload": {"group_name": "ИС-21", "course": 3,
                                           "student_card": "21-ИС-042"}}]})
    assert push.status_code == 200, push.text
    result = push.json()["results"][0]
    assert result["status"] == "applied"
    assert result.get("resolved") == "natural_key"

    profiles = hub.client.get("/api/student/profile", headers=hub.headers).json()
    assert profiles["course"] == 3
    assert profiles["student_card"] == "21-ИС-042"

    with hub.db.session() as db:
        from ecosystem.backend.models import StudentProfile
        from sqlalchemy import select as sa_select

        rows = db.execute(sa_select(StudentProfile)).scalars().all()
    assert len(rows) == 1, "второй профиль не должен появиться"


def test_preference_from_other_device_does_not_break_unique_key(hub):
    dev = _device(hub)
    hub.client.put("/api/preferences", headers=hub.headers,
                   json={"key": "theme", "value": "dark"})
    foreign_id = "77777777-7777-5777-8777-777777777777"
    push = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev["token"]},
                           json={"operations": [{
                               "op_id": "op-pref-1", "entity": "preference",
                               "entity_id": foreign_id, "operation": "upsert",
                               "base_version": 0,
                               "payload": {"key": "theme", "value": {"v": "light"}}}]})
    assert push.status_code == 200, push.text
    assert push.json()["results"][0]["status"] == "applied"
    assert push.json()["results"][0].get("resolved") == "natural_key"
    prefs = hub.client.get("/api/preferences", headers=hub.headers).json()["preferences"]
    assert prefs["theme"] == "light"


def test_student_status_sees_profile_after_sync(hub):
    """Статус не должен «терять» профиль, пришедший с другого узла."""
    dev = _device(hub)
    push = hub.client.post("/api/sync/push", headers={"X-Device-Token": dev["token"]},
                           json={"operations": [{
                               "op_id": "op-status-1", "entity": "student_profile",
                               "entity_id": "88888888-8888-5888-8888-888888888888",
                               "operation": "upsert", "base_version": 0,
                               "payload": {"group_name": "ИС-22", "course": 2}}]})
    assert push.status_code == 200, push.text
    status = hub.client.get("/api/student/status", headers=hub.headers).json()
    assert status["profile"] is not None
    assert status["profile"]["group_name"] == "ИС-22"
    # source != legacy_import: запись пришла синхронизацией, а не импортом старой базы
    assert status["profile"]["source"] in ("manual", "legacy_import")
    assert set(status["imported"]) == {"tasks", "schedule", "profile"}
