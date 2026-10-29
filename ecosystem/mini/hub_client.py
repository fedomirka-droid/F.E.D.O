"""HTTP-клиент HUB для Telegram-бота (никакой своей БД задач)."""
from __future__ import annotations

from typing import Any

import httpx


class HubError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HubClient:
    """Все запросы идут с сервисным токеном бота; права ограничены HUB-ом."""

    def __init__(self, base_url: str, bot_token: str, timeout: float = 15.0,
                 client: httpx.AsyncClient | None = None):
        self.base_url = (base_url or "").rstrip("/")
        self.bot_token = bot_token
        self._client = client
        self._timeout = timeout

    def _http(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=self._timeout)

    @property
    def headers(self) -> dict:
        return {"X-Bot-Token": self.bot_token}

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        client = self._http()
        owns = self._client is None
        try:
            resp = await client.request(method, f"{self.base_url}{path}",
                                        headers=self.headers, **kwargs)
            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    detail = resp.text[:200]
                raise HubError(detail or f"HTTP {resp.status_code}", resp.status_code)
            return resp.json()
        except httpx.HTTPError as exc:
            raise HubError(f"HUB недоступен: {type(exc).__name__}") from exc
        finally:
            if owns:
                await client.aclose()

    async def accounts(self) -> dict:
        return await self._request("GET", "/api/bot/accounts")

    async def link(self, code: str, telegram_id: int, username: str = "") -> dict:
        return await self._request("POST", "/api/bot/link",
                                   json={"code": code.strip().upper(),
                                         "telegram_id": telegram_id, "username": username})

    async def today(self, telegram_id: int) -> dict:
        return await self._request("GET", "/api/bot/today", params={"telegram_id": telegram_id})

    async def tasks(self, telegram_id: int) -> dict:
        return await self._request("GET", "/api/bot/tasks", params={"telegram_id": telegram_id})

    async def schedule(self, telegram_id: int, day: str = "today") -> dict:
        return await self._request("GET", "/api/bot/schedule",
                                   params={"telegram_id": telegram_id, "day": day})

    async def devices(self, telegram_id: int) -> dict:
        return await self._request("GET", "/api/bot/devices", params={"telegram_id": telegram_id})

    async def status(self, telegram_id: int) -> dict:
        return await self._request("GET", "/api/bot/status", params={"telegram_id": telegram_id})

    async def task_action(self, telegram_id: int, task_id: str, action: str,
                          minutes: int = 0) -> dict:
        return await self._request("POST", f"/api/bot/tasks/{task_id}/action",
                                   json={"telegram_id": telegram_id, "action": action,
                                         "minutes": minutes})

    async def create_task(self, telegram_id: int, title: str,
                          due_at: str | None = None, priority: str = "normal") -> dict:
        return await self._request("POST", "/api/bot/tasks",
                                   json={"telegram_id": telegram_id, "title": title,
                                         "due_at": due_at, "priority": priority})

    async def device_command(self, telegram_id: int, device_id: str, action: str,
                             params: dict | None = None) -> dict:
        return await self._request("POST", f"/api/bot/devices/{device_id}/command",
                                   json={"telegram_id": telegram_id, "action": action,
                                         "params": params or {}})

    async def ask_ai(self, telegram_id: int, message: str, mode: str | None = None) -> dict:
        return await self._request("POST", "/api/bot/ai",
                                   json={"telegram_id": telegram_id, "message": message,
                                         "mode": mode})

    async def reminders(self, telegram_id: int, window_minutes: int = 60) -> dict:
        return await self._request("GET", "/api/bot/reminders",
                                   params={"telegram_id": telegram_id,
                                           "window_minutes": window_minutes})
