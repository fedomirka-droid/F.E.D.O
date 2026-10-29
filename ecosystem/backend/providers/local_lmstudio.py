"""Локальная модель устройства через LM Studio (OpenAI-compatible)."""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from .base import ChatRequest, ChatResponse, ProviderError


def _base(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1/models", "/v1"):
        if u.endswith(suffix):
            u = u[: -len(suffix)]
            break
    return u


class LocalLMStudioProvider:
    name = "local"
    is_cloud = False
    cost_per_1m_in = 0.0
    cost_per_1m_out = 0.0

    def __init__(self, base_url: str, model: str = "", client: httpx.AsyncClient | None = None,
                 timeout: float = 120.0):
        self.base_url = _base(base_url)
        self.model = model
        self._client = client
        self._timeout = timeout

    def _http(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=self._timeout)

    async def _close(self, client: httpx.AsyncClient) -> None:
        if self._client is None:
            await client.aclose()

    async def list_models(self) -> list[str]:
        client = self._http()
        try:
            resp = await client.get(f"{self.base_url}/v1/models")
            resp.raise_for_status()
            data = resp.json()
            return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        except Exception:
            return []
        finally:
            await self._close(client)

    async def available(self) -> bool:
        return bool(await self.list_models())

    async def resolve_model(self) -> str:
        if self.model:
            return self.model
        models = await self.list_models()
        if not models:
            raise ProviderError("LM Studio недоступна или модель не загружена", status=None)
        return models[0]

    def _payload(self, request: ChatRequest, model: str, stream: bool) -> dict:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages += [m.as_dict() for m in request.messages]
        return {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }

    async def chat(self, request: ChatRequest) -> ChatResponse:
        client = self._http()
        try:
            model = await self.resolve_model()
            resp = await client.post(f"{self.base_url}/v1/chat/completions",
                                     json=self._payload(request, model, False))
            if resp.status_code >= 400:
                raise ProviderError(f"LM Studio HTTP {resp.status_code}", status=resp.status_code)
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return ChatResponse(
                text=text, provider=self.name, model=model,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
            )
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(f"LM Studio недоступна: {type(exc).__name__}") from exc
        finally:
            await self._close(client)

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        client = self._http()
        try:
            model = await self.resolve_model()
            async with client.stream("POST", f"{self.base_url}/v1/chat/completions",
                                     json=self._payload(request, model, True)) as resp:
                if resp.status_code >= 400:
                    raise ProviderError(f"LM Studio HTTP {resp.status_code}", status=resp.status_code)
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        import json

                        delta = json.loads(chunk)["choices"][0].get("delta", {})
                    except Exception:
                        continue
                    if delta.get("content"):
                        yield delta["content"]
        except httpx.HTTPError as exc:
            raise ProviderError(f"LM Studio недоступна: {type(exc).__name__}") from exc
        finally:
            await self._close(client)
