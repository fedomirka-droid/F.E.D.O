"""AI-шлюз GPU-узла: подпись, свежесть, права."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from ecosystem.agent.gateway import GatewayConfig, create_gateway

DEVICE_ID = "device-uuid-1"
SECRET = "channel-secret"


def _sign(body: dict, ts: str | None = None, secret: str = SECRET) -> tuple[str, str]:
    payload = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    ts = ts or str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return payload, signature


def _gateway(ai_response: dict | None = None, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen2.5-14b"}]})
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        return httpx.Response(200, json=ai_response or {
            "model": "qwen2.5-14b",
            "choices": [{"message": {"content": "привет с RTX 3080"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = GatewayConfig(DEVICE_ID, SECRET, "http://127.0.0.1:1234/v1")
    return TestClient(create_gateway(config, client=client))


def test_health_is_public():
    app = _gateway()
    resp = app.get("/api/ai/health")
    assert resp.status_code == 200
    assert resp.json()["ai_available"] is True


def test_signed_request_passes_and_returns_answer():
    app = _gateway()
    body = {"messages": [{"role": "user", "content": "привет"}], "temperature": 0.4,
            "max_tokens": 100}
    payload, signature = _sign(body)
    resp = app.post("/api/ai/chat", content=payload,
                    headers={"X-FEDO-Device": DEVICE_ID,
                             "X-FEDO-Timestamp": str(int(time.time())),
                             "X-FEDO-Signature": signature,
                             "Content-Type": "application/json"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["text"] == "привет с RTX 3080"
    assert data["usage"]["completion_tokens"] == 4
    assert data["device_id"] == DEVICE_ID


def test_missing_signature_rejected():
    app = _gateway()
    payload, _ = _sign({"messages": []})
    assert app.post("/api/ai/chat", content=payload).status_code == 401


def test_wrong_signature_rejected():
    app = _gateway()
    payload, _ = _sign({"messages": []}, secret="wrong-secret")
    resp = app.post("/api/ai/chat", content=payload,
                    headers={"X-FEDO-Device": DEVICE_ID,
                             "X-FEDO-Timestamp": str(int(time.time())),
                             "X-FEDO-Signature": _sign({"other": 1})[1]})
    assert resp.status_code == 401


def test_stale_timestamp_rejected():
    app = _gateway()
    body = {"messages": [{"role": "user", "content": "hi"}]}
    old_ts = str(int(time.time()) - 3600)
    payload, signature = _sign(body, ts=old_ts)
    resp = app.post("/api/ai/chat", content=payload,
                    headers={"X-FEDO-Device": DEVICE_ID, "X-FEDO-Timestamp": old_ts,
                             "X-FEDO-Signature": signature})
    assert resp.status_code == 401 and "просрочена" in resp.json()["detail"]


def test_unknown_device_rejected():
    app = _gateway()
    body = {"messages": []}
    payload, signature = _sign(body)
    resp = app.post("/api/ai/chat", content=payload,
                    headers={"X-FEDO-Device": "other-device",
                             "X-FEDO-Timestamp": str(int(time.time())),
                             "X-FEDO-Signature": signature})
    assert resp.status_code == 403


def test_upstream_failure_is_fenced():
    app = _gateway(status=500)
    body = {"messages": [{"role": "user", "content": "hi"}]}
    payload, signature = _sign(body)
    resp = app.post("/api/ai/chat", content=payload,
                    headers={"X-FEDO-Device": DEVICE_ID,
                             "X-FEDO-Timestamp": str(int(time.time())),
                             "X-FEDO-Signature": signature})
    assert resp.status_code == 502


async def test_remote_node_provider_uses_canonical_signature():
    from ecosystem.backend.providers.remote_node import RemoteNodeProvider

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"ok": True})
        seen["body"] = request.content.decode()
        seen["sig"] = request.headers["x-fedo-signature"]
        seen["ts"] = request.headers["x-fedo-timestamp"]
        return httpx.Response(200, json={"text": "ответ узла", "model": "qwen",
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RemoteNodeProvider("http://home-pc:8790", DEVICE_ID, SECRET, client=client)
    from ecosystem.backend.providers.base import ChatMessage, ChatRequest

    response = await provider.chat(ChatRequest(messages=[ChatMessage("user", "привет")]))
    assert response.text == "ответ узла"
    expected = hmac.new(SECRET.encode(), f"{seen['ts']}.{seen['body']}".encode(),
                        hashlib.sha256).hexdigest()
    assert seen["sig"] == expected
