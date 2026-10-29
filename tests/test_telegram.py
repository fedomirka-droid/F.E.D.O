"""Проверки 14–15: привязка Telegram, права бота, чужие устройства недоступны."""
from __future__ import annotations

BOT_HEADERS = {"X-Bot-Token": "bot-service-token-for-tests"}
TG_ID = 555000111


def test_bot_disabled_without_service_token(harness):
    resp = harness.client.get("/api/bot/today", params={"telegram_id": TG_ID})
    assert resp.status_code == 503


def test_bot_rejects_wrong_service_token(make_harness):
    h = make_harness("hub", bot_service_token="bot-service-token-for-tests")
    h.setup_owner()
    resp = h.client.get("/api/bot/today", params={"telegram_id": TG_ID},
                        headers={"X-Bot-Token": "wrong"})
    assert resp.status_code == 403


def test_link_flow_and_access(make_harness):
    h = make_harness("hub", bot_service_token="bot-service-token-for-tests")
    h.setup_owner()

    unlinked = h.client.get("/api/bot/today", params={"telegram_id": TG_ID}, headers=BOT_HEADERS)
    assert unlinked.status_code == 403

    link = h.client.post("/api/telegram/link", headers=h.headers).json()
    assert link["code"] and link["ttl_minutes"] >= 1

    claimed = h.client.post("/api/bot/link", headers=BOT_HEADERS,
                            json={"code": link["code"], "telegram_id": TG_ID,
                                  "username": "fedomirka"})
    assert claimed.status_code == 200 and claimed.json()["linked"] is True

    today = h.client.get("/api/bot/today", params={"telegram_id": TG_ID}, headers=BOT_HEADERS)
    assert today.status_code == 200

    again = h.client.post("/api/bot/link", headers=BOT_HEADERS,
                          json={"code": link["code"], "telegram_id": 999})
    assert again.status_code == 409  # код одноразовый

    accounts = h.client.get("/api/telegram/accounts", headers=h.headers).json()["accounts"]
    assert len(accounts) == 1 and accounts[0]["telegram_id"] == TG_ID

    unlink = h.client.delete(f"/api/telegram/accounts/{accounts[0]['id']}", headers=h.headers)
    assert unlink.status_code == 200
    assert h.client.get("/api/bot/today", params={"telegram_id": TG_ID},
                        headers=BOT_HEADERS).status_code == 403


def test_expired_code_rejected(make_harness):
    h = make_harness("hub", bot_service_token="bot-service-token-for-tests",
                     telegram_link_ttl_minutes=1)
    h.setup_owner()
    code = h.client.post("/api/telegram/link", headers=h.headers).json()["code"]

    from datetime import timedelta

    from ecosystem.backend.db import utcnow
    from ecosystem.backend.models import TelegramLinkCode

    with h.db.session() as db:
        row = db.query(TelegramLinkCode).first()
        row.expires_at = utcnow() - timedelta(minutes=1)

    resp = h.client.post("/api/bot/link", headers=BOT_HEADERS,
                         json={"code": code, "telegram_id": TG_ID})
    assert resp.status_code == 410


def test_wrong_code_counted_and_limited(make_harness):
    h = make_harness("hub", bot_service_token="bot-service-token-for-tests")
    h.setup_owner()
    h.client.post("/api/telegram/link", headers=h.headers)
    for _ in range(6):
        resp = h.client.post("/api/bot/link", headers=BOT_HEADERS,
                             json={"code": "BADCODE1", "telegram_id": TG_ID})
    assert resp.status_code in (404, 429)


def _linked_hub(make_harness):
    h = make_harness("hub", bot_service_token="bot-service-token-for-tests")
    h.setup_owner()
    code = h.client.post("/api/telegram/link", headers=h.headers).json()["code"]
    h.client.post("/api/bot/link", headers=BOT_HEADERS,
                  json={"code": code, "telegram_id": TG_ID, "username": "owner"})
    return h


def test_bot_reads_tasks_and_schedule(make_harness):
    h = _linked_hub(make_harness)
    task = h.client.post("/api/tasks", headers=h.headers,
                         json={"title": "Курсовая", "due_at": "2026-10-30T18:00:00Z"}).json()

    tasks = h.client.get("/api/bot/tasks", params={"telegram_id": TG_ID}, headers=BOT_HEADERS).json()
    assert [t["id"] for t in tasks["tasks"]] == [task["id"]]

    action = h.client.post(f"/api/bot/tasks/{task['id']}/action", headers=BOT_HEADERS,
                           json={"telegram_id": TG_ID, "action": "complete"}).json()
    assert action["status"] == "done"

    schedule = h.client.get("/api/bot/schedule", params={"telegram_id": TG_ID, "day": "tomorrow"},
                            headers=BOT_HEADERS)
    assert schedule.status_code == 200 and "entries" in schedule.json()


def test_bot_cannot_touch_foreign_device(make_harness):
    h = _linked_hub(make_harness)
    device = h.client.post("/api/devices", headers=h.headers,
                           json={"name": "ThinkPad", "kind": "desktop"}).json()

    from ecosystem.backend.models import Device, Owner
    from ecosystem.backend.security import hash_password, new_token, token_hash

    with h.db.session() as db:
        stranger = Owner(username="stranger", password_hash=hash_password("Stranger123!"))
        db.add(stranger)
        db.flush()
        foreign = Device(owner_id=stranger.id, name="Чужой ПК", kind="desktop",
                         token_hash=token_hash(new_token()))
        db.add(foreign)
        db.flush()
        foreign_id = foreign.id

    resp = h.client.post(f"/api/bot/devices/{foreign_id}/command", headers=BOT_HEADERS,
                         json={"telegram_id": TG_ID, "action": "status"})
    assert resp.status_code == 404

    own = h.client.post(f"/api/bot/devices/{device['device']['id']}/command", headers=BOT_HEADERS,
                        json={"telegram_id": TG_ID, "action": "status"})
    assert own.status_code == 200 and own.json()["status"] == "approved"

    dangerous = h.client.post(f"/api/bot/devices/{device['device']['id']}/command",
                              headers=BOT_HEADERS,
                              json={"telegram_id": TG_ID, "action": "sleep"})
    assert dangerous.json()["requires_confirmation"] is True
    assert dangerous.json()["status"] == "awaiting_confirmation"


def test_bot_status_and_ai_endpoint(make_harness):
    h = _linked_hub(make_harness)
    status = h.client.get("/api/bot/status", params={"telegram_id": TG_ID}, headers=BOT_HEADERS)
    assert status.status_code == 200 and "ai_usage" in status.json()

    ai = h.client.post("/api/bot/ai", headers=BOT_HEADERS,
                       json={"telegram_id": TG_ID, "message": "привет"})
    assert ai.status_code == 200
    assert isinstance(ai.json()["text"], str)
