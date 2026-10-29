"""Произвольный HTTPS OpenAI-compatible API (настраиваемый провайдер)."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import ChatRequest, ChatResponse, ProviderError


class OpenAICompatibleProvider:
    def __init__(self, name: str, base_url: str, api_key: str, model: str,
                 client: httpx.AsyncClient | None = None, timeout: float = 60.0,
                 cost_per_1m_in: float = 0.0, cost_per_1m_out: float = 0.0):
        self.name = name
        self.is_cloud = True
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or "gpt-4o-mini"
        self._client = client
        self._timeout = timeout
        self.cost_per_1m_in = cost_per_1m_in
        self.cost_per_1m_out = cost_per_1m_out

    def _http(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=self._timeout)

    async def _close(self, client: httpx.AsyncClient) -> None:
        if self._client is None:
            await client.aclose()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, request: ChatRequest, stream: bool) -> dict:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages += [m.as_dict() for m in request.messages]
        return {"model": self.model, "messages": messages, "temperature": request.temperature,
                "max_tokens": request.max_tokens, "stream": stream}

    async def available(self) -> bool:
        return bool(self.api_key and self.base_url)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not await self.available():
            raise ProviderError(f"{self.name}: провайдер не настроен", retryable=False)
        client = self._http()
        try:
            resp = await client.post(f"{self.base_url}/chat/completions",
                                     headers=self._headers(), json=self._payload(request, False))
            if resp.status_code >= 400:
                raise ProviderError(f"{self.name} HTTP {resp.status_code}", status=resp.status_code)
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
            cost = pt / 1_000_000 * self.cost_per_1m_in + ct / 1_000_000 * self.cost_per_1m_out
            return ChatResponse(text=text, provider=self.name, model=self.model,
                                prompt_tokens=pt, completion_tokens=ct, cost=cost)
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} недоступен: {type(exc).__name__}") from exc
        finally:
            await self._close(client)

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        if not await self.available():
            raise ProviderError(f"{self.name}: провайдер не настроен", retryable=False)
        client = self._http()
        try:
            async with client.stream("POST", f"{self.base_url}/chat/completions",
                                     headers=self._headers(),
                                     json=self._payload(request, True)) as resp:
                if resp.status_code >= 400:
                    raise ProviderError(f"{self.name} HTTP {resp.status_code}", status=resp.status_code)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0].get("delta", {})
                    except Exception:
                        continue
                    if delta.get("content"):
                        yield delta["content"]
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} недоступен: {type(exc).__name__}") from exc
        finally:
            await self._close(client)
