"""Проверки адаптера F.E.D.O. Mini: клиент HUB, форматирование, права."""
from __future__ import annotations

import httpx
import pytest

from ecosystem.mini import formatting as fmt
from ecosystem.mini.hub_client import HubClient, HubError
from ecosystem.mini.keyboards import devices_menu, main_menu, task_actions


def _client(handler) -> HubClient:
    transport = httpx.MockTransport(handler)
    return HubClient("https://hub.example", "bot-token",
                     client=httpx.AsyncClient(transport=transport))


async def test_hub_client_sends_service_token_and_parses():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("x-bot-token")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"tasks": []})

    client = _client(handler)
    data = await client.tasks(555)
    assert data == {"tasks": []}
    assert seen["token"] == "bot-token" and seen["path"] == "/api/bot/tasks"


async def test_hub_client_maps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Аккаунт Telegram не привязан"})

    client = _client(handler)
    with pytest.raises(HubError) as exc:
        await client.today(1)
    assert exc.value.status == 403


async def test_hub_client_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = _client(handler)
    with pytest.raises(HubError) as exc:
        await client.status(1)
    assert "недоступен" in str(exc.value)


def test_format_today_with_lessons_and_tasks():
    text = fmt.format_today({
        "date": "2026-10-29",
        "lessons": [{"start_time": "08:30", "end_time": "10:00", "subject": "Математика",
                     "teacher": "Иванов И.И.", "room": "каб. 215", "lesson_type": "лекц"}],
        "tasks": [{"title": "Курсовая", "status": "in_progress", "priority": "high",
                   "due_at": "2026-10-29T18:00:00Z", "planned_minutes": 60}],
    })
    assert "08:30–10:00" in text and "Математика" in text and "каб. 215" in text
    assert "Курсовая" in text and "в работе" in text


def test_format_empty_day():
    text = fmt.format_today({"date": "2026-10-29", "lessons": [], "tasks": []})
    assert "занятий нет" in text and "активных задач нет" in text


def test_format_devices_and_status():
    devices = fmt.format_devices({"devices": [
        {"name": "ThinkPad", "status": "online", "ai_available": True},
        {"name": "HomePC", "status": "sleeping", "ai_available": True},
    ]})
    assert "ThinkPad" in devices and "HomePC" in devices and "AI доступен" in devices
    status = fmt.format_status({"devices_total": 2, "devices_online": ["ThinkPad"],
                                "ai_mode": "hybrid",
                                "ai_usage": {"today_requests": 3, "today_cloud_requests": 1,
                                             "month_cost": 0.02}})
    assert "1 из 2" in status and "hybrid" in status


def test_escape_html_blocks_injection():
    assert fmt.escape_html("<b>x</b> & y") == "&lt;b&gt;x&lt;/b&gt; &amp; y"


def test_keyboards_contain_required_actions():
    menu = main_menu()
    callbacks = [b.callback_data for row in menu.inline_keyboard for b in row]
    for expected in ("menu:today", "menu:tomorrow", "menu:add", "menu:devices",
                     "menu:ai", "menu:status"):
        assert expected in callbacks

    actions = task_actions("task-1", "todo")
    callbacks = [b.callback_data for row in actions.inline_keyboard for b in row]
    assert "task:start:task-1" in callbacks and "task:complete:task-1" in callbacks

    working = task_actions("task-1", "in_progress")
    callbacks = [b.callback_data for row in working.inline_keyboard for b in row]
    assert "task:extend:task-1" in callbacks

    devices = devices_menu([{"id": "dev-1", "name": "HomePC"}])
    callbacks = [b.callback_data for row in devices.inline_keyboard for b in row]
    assert "device:status:dev-1" in callbacks and "device:sleep:dev-1" in callbacks


async def test_bot_create_task_and_reminders_endpoints(make_harness):
    h = make_harness("hub", bot_service_token="bot-service-token-for-tests")
    h.setup_owner()
    code = h.client.post("/api/telegram/link", headers=h.headers).json()["code"]
    h.client.post("/api/bot/link", headers={"X-Bot-Token": "bot-service-token-for-tests"},
                  json={"code": code, "telegram_id": 777001, "username": "owner"})

    created = h.client.post("/api/bot/tasks", headers={"X-Bot-Token": "bot-service-token-for-tests"},
                            json={"telegram_id": 777001, "title": "Из Telegram",
                                  "due_at": "2026-10-29T20:00:00Z"})
    assert created.status_code == 200 and created.json()["title"] == "Из Telegram"

    reminders = h.client.get("/api/bot/reminders", headers={"X-Bot-Token": "bot-service-token-for-tests"},
                             params={"telegram_id": 777001, "window_minutes": 1440})
    assert reminders.status_code == 200
    accounts = h.client.get("/api/bot/accounts", headers={"X-Bot-Token": "bot-service-token-for-tests"})
    assert accounts.json()["accounts"][0]["telegram_id"] == 777001
