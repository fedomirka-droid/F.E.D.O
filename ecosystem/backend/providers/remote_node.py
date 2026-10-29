"""Удалённая локальная модель домашнего ПК (F.E.D.O. GPU Node).

Запросы подписываются HMAC секретом канала устройства — сам узел
проверяет подпись и владельца. Облаком не считается: это своё железо.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import AsyncIterator

import httpx

from .base import ChatRequest, ChatResponse, ProviderError


class RemoteNodeProvider:
    name = "remote_node"
    is_cloud = False
    cost_per_1m_in = 0.0
    cost_per_1m_out = 0.0

    def __init__(self, node_url: str, device_id: str, channel_secret: str, model: str = "",
                 client: httpx.AsyncClient | None = None, timeout: float = 120.0):
        self.node_url = (node_url or "").rstrip("/")
        self.device_id = device_id
        self.channel_secret = channel_secret
        self.model = model
        self._client = client
        self._timeout = timeout

    def _http(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=self._timeout)

    async def _close(self, client: httpx.AsyncClient) -> None:
        if self._client is None:
            await client.aclose()

    @staticmethod
    def canonical(body: dict) -> str:
        return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _sign(self, body: dict) -> tuple[dict, str]:
        payload = self.canonical(body)
        ts = str(int(time.time()))
        signature = hmac.new(self.channel_secret.encode(), f"{ts}.{payload}".encode(),
                             hashlib.sha256).hexdigest()
        headers = {"X-FEDO-Device": self.device_id, "X-FEDO-Timestamp": ts,
                   "X-FEDO-Signature": signature, "Content-Type": "application/json"}
        return headers, payload

    async def available(self) -> bool:
        if not (self.node_url and self.channel_secret):
            return False
        client = self._http()
        try:
            resp = await client.get(f"{self.node_url}/api/ai/health", timeout=3.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
        finally:
            await self._close(client)

    def _body(self, request: ChatRequest, stream: bool) -> dict:
        return {
            "model": self.model or "auto",
            "messages": [*([{"role": "system", "content": request.system}] if request.system else []),
                         *[m.as_dict() for m in request.messages]],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not (self.node_url and self.channel_secret):
            raise ProviderError("Домашний AI-узел не настроен", retryable=False)
        body = self._body(request, False)
        client = self._http()
        try:
            headers, payload = self._sign(body)
            resp = await client.post(f"{self.node_url}/api/ai/chat", content=payload, headers=headers)
            if resp.status_code >= 400:
                raise ProviderError(f"Домашний узел HTTP {resp.status_code}", status=resp.status_code)
            data = resp.json()
            usage = data.get("usage") or {}
            return ChatResponse(text=data.get("text", ""), provider=self.name,
                                model=data.get("model", self.model or "home-node"),
                                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                                completion_tokens=int(usage.get("completion_tokens") or 0))
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(f"Домашний узел недоступен: {type(exc).__name__}") from exc
        finally:
            await self._close(client)

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        # Узел отдаёт один JSON (простая и надёжная реализация); стрим эмулируем.
        response = await self.chat(request)
        if response.text:
            yield response.text
