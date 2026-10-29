"""Google Gemini (HTTPS, ключ только в заголовке, не в URL и не в логах)."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import ChatRequest, ChatResponse, ProviderError

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"
    is_cloud = True
    cost_per_1m_in = 0.075
    cost_per_1m_out = 0.30

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash",
                 base_url: str = DEFAULT_BASE, client: httpx.AsyncClient | None = None,
                 timeout: float = 60.0):
        self.api_key = api_key or ""
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout

    def _http(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=self._timeout)

    async def _close(self, client: httpx.AsyncClient) -> None:
        if self._client is None:
            await client.aclose()

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _payload(self, request: ChatRequest) -> dict:
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
        ]
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }
        if request.system:
            payload["systemInstruction"] = {"parts": [{"text": request.system}]}
        return payload

    async def available(self) -> bool:
        return bool(self.api_key)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.api_key:
            raise ProviderError("Gemini API-ключ не настроен", retryable=False)
        client = self._http()
        try:
            resp = await client.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                headers=self._headers(), json=self._payload(request),
            )
            if resp.status_code >= 400:
                raise ProviderError(f"Gemini HTTP {resp.status_code}", status=resp.status_code)
            data = resp.json()
            text = _extract_text(data)
            usage = data.get("usageMetadata") or {}
            pt = int(usage.get("promptTokenCount") or 0)
            ct = int(usage.get("candidatesTokenCount") or 0)
            cost = pt / 1_000_000 * self.cost_per_1m_in + ct / 1_000_000 * self.cost_per_1m_out
            return ChatResponse(text=text, provider=self.name, model=self.model,
                                prompt_tokens=pt, completion_tokens=ct, cost=cost)
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini недоступен: {type(exc).__name__}") from exc
        finally:
            await self._close(client)

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        if not self.api_key:
            raise ProviderError("Gemini API-ключ не настроен", retryable=False)
        client = self._http()
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/models/{self.model}:streamGenerateContent",
                params={"alt": "sse"},
                headers=self._headers(), json=self._payload(request),
            ) as resp:
                if resp.status_code >= 400:
                    raise ProviderError(f"Gemini HTTP {resp.status_code}", status=resp.status_code)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if not chunk:
                        continue
                    try:
                        parsed = json.loads(chunk)
                    except Exception:
                        continue
                    text = _extract_text(parsed)
                    if text:
                        yield text
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini недоступен: {type(exc).__name__}") from exc
        finally:
            await self._close(client)


def _extract_text(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError):
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise ProviderError(f"Gemini заблокировал запрос: {block}", retryable=False)
        return ""
