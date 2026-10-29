"""Проверки 1–2: регистрация владельца, вход/выход, сессии, лимиты."""
from __future__ import annotations

from tests.conftest import PASSWORD


def test_owner_setup_once_and_public_registration_disabled(harness):
    again = harness.client.post("/api/auth/setup",
                                json={"username": "second", "password": "AnotherPass1"})
    assert again.status_code == 409

    status = harness.client.get("/api/auth/status").json()
    assert status["owner_exists"] is True
    assert status["public_registration"] is False


def test_login_logout_and_session_revocation(harness):
    login = harness.client.post("/api/auth/login",
                                json={"username": "owner", "password": PASSWORD})
    assert login.status_code == 200
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert harness.client.get("/api/auth/me", headers=headers).status_code == 200

    assert harness.client.post("/api/auth/logout", headers=headers).status_code == 200
    assert harness.client.get("/api/auth/me", headers=headers).status_code == 401

    # отзыв всех сессий
    login2 = harness.client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    token2 = login2.json()["token"]
    h2 = {"Authorization": f"Bearer {token2}"}
    sessions = harness.client.get("/api/auth/sessions", headers=h2).json()["sessions"]
    assert len(sessions) >= 1
    current = next(s for s in sessions if s["current"])
    harness.client.delete(f"/api/auth/sessions/{current['id']}", headers=h2)
    assert harness.client.get("/api/auth/me", headers=h2).status_code == 401


def test_wrong_password_and_unknown_user(harness):
    assert harness.client.post("/api/auth/login", json={"username": "owner", "password": "badpass"}).status_code == 401
    assert harness.client.post("/api/auth/login", json={"username": "ghost", "password": "whatever1"}).status_code == 401


def test_login_rate_limit(harness):
    codes = []
    for _ in range(12):
        codes.append(harness.client.post("/api/auth/login",
                                         json={"username": "owner", "password": "wrongpass"}).status_code)
    assert 429 in codes


def test_password_change_revokes_other_sessions(harness):
    other = harness.client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    other_token = other.json()["token"]
    resp = harness.client.post("/api/auth/password", headers=harness.headers,
                               json={"current_password": PASSWORD, "new_password": "NewPassword123"})
    assert resp.status_code == 200
    assert harness.client.get("/api/auth/me", headers={"Authorization": f"Bearer {other_token}"}).status_code == 401
    assert harness.client.post("/api/auth/login", json={"username": "owner", "password": "NewPassword123"}).status_code == 200


def test_weak_password_rejected(harness, make_harness):
    fresh = make_harness("desktop")
    resp = fresh.client.post("/api/auth/setup", json={"username": "owner", "password": "short"})
    assert resp.status_code == 422


def test_unauthenticated_access_denied(harness):
    for path in ("/api/tasks", "/api/devices", "/api/sync/status", "/api/ai/settings"):
        assert harness.client.get(path).status_code == 401


def test_api_rate_limit_applies(harness, make_harness):
    limited = make_harness("desktop", api_rate_limit=5, api_rate_window=60)
    limited.setup_owner()
    codes = [limited.client.get("/api/tasks", headers=limited.headers).status_code for _ in range(9)]
    assert 429 in codes
