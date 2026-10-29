"""AI-шлюз F.E.D.O. GPU Node.

Домашний ПК выставляет этот шлюз в локальной сети / защищённом канале
(WireGuard/Tailscale). Любой запрос обязан иметь HMAC-подпись секретом канала
устройства и свежий timestamp — иначе 401. Шлюз лишь проксирует запрос к
локальной LM Studio, никаких shell-команд.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

MAX_SKEW_SECONDS = 300
MAX_BODY_BYTES = 256 * 1024


class GatewayConfig:
    def __init__(self, device_id: str, channel_secret: str, ai_url: str,
                 model: str = "", timeout: float = 120.0):
        self.device_id = device_id
        self.channel_secret = channel_secret
        self.ai_url = (ai_url or "http://127.0.0.1:1234/v1").rstrip("/")
        self.model = model
        self.timeout = timeout


def verify_signature(config: GatewayConfig, headers: dict, raw_body: bytes) -> None:
    device = headers.get("x-fedo-device", "")
    ts = headers.get("x-fedo-timestamp", "")
    signature = headers.get("x-fedo-signature", "")
    if not (device and ts and signature):
        raise HTTPException(status_code=401, detail="нет подписи устройства")
    if device != config.device_id:
        raise HTTPException(status_code=403, detail="неизвестное устройство")
    try:
        skew = abs(time.time() - int(ts))
    except ValueError:
        raise HTTPException(status_code=401, detail="некорректный timestamp")
    if skew > MAX_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="подпись просрочена")
    body = raw_body.decode("utf-8")
    expected = hmac.new(config.channel_secret.encode(), f"{ts}.{body}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="неверная подпись")


def create_gateway(config: GatewayConfig, client: httpx.AsyncClient | None = None) -> FastAPI:
    app = FastAPI(title="F.E.D.O. GPU Node AI gateway", version="2.0.0")

    @app.get("/api/ai/health")
    async def health() -> dict:
        """Публичный health: только факт доступности, без деталей."""
        available = False
        try:
            http = client or httpx.AsyncClient(timeout=3.0)
            try:
                resp = await http.get(f"{config.ai_url}/models")
                available = resp.status_code == 200 and "data" in resp.json()
            finally:
                if client is None:
                    await http.aclose()
        except Exception:
            available = False
        return {"ok": True, "ai_available": available, "device_id": config.device_id}

    @app.post("/api/ai/chat")
    async def chat(request: Request) -> JSONResponse:
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="запрос слишком большой")
        verify_signature(config, dict(request.headers), raw)
        try:
            body: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="некорректный JSON")

        payload = {
            "model": config.model or body.get("model") or "local-model",
            "messages": body.get("messages") or [],
            "temperature": body.get("temperature", 0.6),
            "max_tokens": body.get("max_tokens", 800),
        }
        http = client or httpx.AsyncClient(timeout=config.timeout)
        try:
            resp = await http.post(f"{config.ai_url}/chat/completions", json=payload)
            if resp.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"AI-узел ответил {resp.status_code}")
            data = resp.json()
            usage = data.get("usage") or {}
            text = data["choices"][0]["message"]["content"]
            return JSONResponse({
                "text": text,
                "model": data.get("model") or payload["model"],
                "device_id": config.device_id,
                "usage": {"prompt_tokens": usage.get("prompt_tokens", 0),
                          "completion_tokens": usage.get("completion_tokens", 0)},
            })
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"AI-узел недоступен: {type(exc).__name__}")
        finally:
            if client is None:
                await http.aclose()

    return app
