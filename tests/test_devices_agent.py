"""Проверки 16, 8: устройства, безопасные команды, агент, Wake-on-LAN."""
from __future__ import annotations

import platform

import pytest

from ecosystem.agent.runtime import AgentExecutor, AgentPolicy
from ecosystem.agent.wake import magic_packet, normalize_mac
from ecosystem.backend.security import sign_payload


def _register(hub, name="HomePC", kind="gpu", caps=("ai",)):
    resp = hub.client.post("/api/devices", headers=hub.headers,
                           json={"name": name, "kind": kind, "capabilities": list(caps)})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_register_returns_token_once_and_lists_device(hub):
    data = _register(hub)
    assert data["token"].startswith("dev_")
    assert data["channel_secret"]
    device = data["device"]
    assert device["status"] == "offline"

    listed = hub.client.get("/api/devices", headers=hub.headers).json()
    names = [d["name"] for d in listed["devices"]]
    assert "HomePC" in names
    assert all("token" not in d for d in listed["devices"])

    duplicate = hub.client.post("/api/devices", headers=hub.headers,
                                json={"name": "HomePC", "kind": "gpu"})
    assert duplicate.status_code == 409


def test_heartbeat_marks_device_online(hub):
    data = _register(hub)
    resp = hub.client.post("/api/agent/heartbeat", headers={"X-Device-Token": data["token"]},
                           json={"status": "online", "metrics": {"cpu_percent": 12.5, "gpu": {"name": "RTX 3080"}},
                                 "ai_available": True, "platform": "Windows 11"})
    assert resp.status_code == 200
    device = next(d for d in hub.client.get("/api/devices", headers=hub.headers).json()["devices"]
                  if d["id"] == data["device"]["id"])
    assert device["status"] == "online"
    assert device["ai_available"] is True
    assert device["metrics"]["cpu_percent"] == 12.5
    assert device["platform"] == "Windows 11"


def test_safe_command_reaches_agent_signed(hub):
    data = _register(hub)
    cmd = hub.client.post(f"/api/devices/{data['device']['id']}/commands", headers=hub.headers,
                          json={"action": "status"}).json()
    assert cmd["status"] == "approved" and cmd["requires_confirmation"] is False

    poll = hub.client.get("/api/agent/poll", headers={"X-Device-Token": data["token"]}).json()
    assert len(poll["commands"]) == 1
    delivered = poll["commands"][0]
    assert delivered["action"] == "status"
    expected = sign_payload(data["channel_secret"], {
        "command_id": delivered["command_id"], "device_id": delivered["device_id"],
        "action": delivered["action"], "params": delivered["params"]})
    assert delivered["signature"] == expected

    done = hub.client.post("/api/agent/result", headers={"X-Device-Token": data["token"]},
                           json={"command_id": delivered["command_id"], "ok": True,
                                 "result": {"hostname": "home-pc"}})
    assert done.status_code == 200
    commands = hub.client.get(f"/api/devices/{data['device']['id']}/commands",
                              headers=hub.headers).json()["commands"]
    assert commands[0]["status"] == "done"
    assert commands[0]["result"]["hostname"] == "home-pc"


def test_dangerous_command_requires_confirmation(hub):
    data = _register(hub)
    cmd = hub.client.post(f"/api/devices/{data['device']['id']}/commands", headers=hub.headers,
                          json={"action": "sleep"}).json()
    assert cmd["requires_confirmation"] is True
    assert cmd["status"] == "awaiting_confirmation"

    poll = hub.client.get("/api/agent/poll", headers={"X-Device-Token": data["token"]}).json()
    assert poll["commands"] == []  # без подтверждения не доставляется

    confirmed = hub.client.post(f"/api/devices/commands/{cmd['id']}/confirm", headers=hub.headers)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "approved"

    poll = hub.client.get("/api/agent/poll", headers={"X-Device-Token": data["token"]}).json()
    assert [c["action"] for c in poll["commands"]] == ["sleep"]


def test_rejected_command_never_delivered(hub):
    data = _register(hub)
    cmd = hub.client.post(f"/api/devices/{data['device']['id']}/commands", headers=hub.headers,
                          json={"action": "wol", "params": {"mac": "AA:BB:CC:DD:EE:FF"}}).json()
    hub.client.post(f"/api/devices/commands/{cmd['id']}/reject", headers=hub.headers)
    poll = hub.client.get("/api/agent/poll", headers={"X-Device-Token": data["token"]}).json()
    assert poll["commands"] == []


@pytest.mark.parametrize("action,params", [
    ("shell", {"cmd": "whoami"}),
    ("exec", {"command": "rm -rf /"}),
    ("status", {"cmd": "whoami"}),
    ("sleep", {"force": "1"}),
    ("wol", {"mac": "not-a-mac"}),  # формат проверяется агентом, а не API
])
def test_forbidden_commands_and_params(hub, action, params):
    data = _register(hub)
    resp = hub.client.post(f"/api/devices/{data['device']['id']}/commands", headers=hub.headers,
                           json={"action": action, "params": params})
    if action == "wol":
        assert resp.status_code == 200  # параметр разрешён, но MAC проверит агент
    else:
        assert resp.status_code == 400


def test_revoked_device_cannot_use_agent_api(hub):
    data = _register(hub)
    hub.client.post(f"/api/devices/{data['device']['id']}/revoke", headers=hub.headers)
    assert hub.client.get("/api/agent/poll",
                          headers={"X-Device-Token": data["token"]}).status_code == 401


def test_rotate_token_invalidates_old(hub):
    data = _register(hub)
    rotated = hub.client.post(f"/api/devices/{data['device']['id']}/rotate-token",
                              headers=hub.headers).json()
    assert rotated["token"] != data["token"]
    assert hub.client.get("/api/agent/poll",
                          headers={"X-Device-Token": data["token"]}).status_code == 401
    assert hub.client.get("/api/agent/poll",
                          headers={"X-Device-Token": rotated["token"]}).status_code == 200


def test_commands_are_owner_scoped(hub):
    from ecosystem.backend.models import Owner
    from ecosystem.backend.security import hash_password

    data = _register(hub, "Другой ПК")
    with hub.db.session() as db:
        intruder = Owner(username="intruder", password_hash=hash_password("Intruder123!"))
        db.add(intruder)
        db.flush()
        intruder_id = intruder.id

    with hub.db.session() as db:
        from ecosystem.backend.models import UserSession
        from ecosystem.backend.db import utcnow
        from datetime import timedelta
        from ecosystem.backend.security import new_token, token_hash

        token = new_token()
        db.add(UserSession(owner_id=intruder_id, token_hash=token_hash(token),
                           expires_at=utcnow() + timedelta(hours=1)))
    intruder_headers = {"Authorization": f"Bearer {token}"}
    assert hub.client.post(f"/api/devices/{data['device']['id']}/commands",
                           headers=intruder_headers, json={"action": "status"}).status_code == 404


def test_agent_executor_respects_policy():
    denied = AgentExecutor(AgentPolicy(simulate=True))
    assert denied.execute("sleep")["denied"] is True
    assert denied.execute("ai_start")["denied"] is True
    assert denied.execute("wol", {"mac": "AA:BB:CC:DD:EE:FF"})["denied"] is True

    allowed = AgentExecutor(AgentPolicy(simulate=True, allow_power=True, allow_wol=True,
                                        allow_ai_control=True,
                                        ai_start_command=["echo", "start"],
                                        ai_stop_command=["echo", "stop"]))
    assert allowed.execute("ai_start")["ok"] is True
    assert allowed.execute("wol", {"mac": "AA:BB:CC:DD:EE:FF"})["ok"] is True
    assert allowed.execute("shell", {"cmd": "ls"})["ok"] is False


def test_agent_status_and_stats():
    executor = AgentExecutor(AgentPolicy(simulate=True))
    status = executor.execute("status")
    assert status["ok"] is True and "platform" in status
    stats = executor.execute("stats")
    assert stats["ok"] is True and "cpu_percent" in stats


def test_wol_packet_and_mac_normalization():
    packet = magic_packet("AA:BB:CC:DD:EE:FF")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:12] == bytes.fromhex("aabbccddeeff")
    assert normalize_mac("aabb.ccdd.eeff") == bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError):
        normalize_mac("zz:zz")
