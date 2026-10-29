"""F.E.D.O. Mini — Aiogram 3 бот.

Запуск (на VPS рядом с HUB или локально):
    export FEDO_TELEGRAM_BOT_TOKEN=...
    export FEDO_HUB_URL=https://hub.example
    export FEDO_BOT_SERVICE_TOKEN=...
    python -m ecosystem.mini

Бот не имеет своей базы задач: всё идёт через HUB и его права доступа.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from . import formatting as fmt
from .hub_client import HubClient, HubError
from .keyboards import back_menu, devices_menu, main_menu, task_actions

logger = logging.getLogger("fedo.mini")

router = Router()
_hub: HubClient | None = None
_notified: set[str] = set()

HELP_TEXT = (
    "<b>F.E.D.O. Mini</b>\n"
    "/start — меню\n"
    "/today — занятия и задачи на сегодня\n"
    "/tomorrow — план на завтра\n"
    "/tasks — все задачи\n"
    "/schedule — расписание (сегодня/завтра)\n"
    "/devices — устройства и статус ПК\n"
    "/ai &lt;вопрос&gt; — спросить AI\n"
    "/status — статус экосистемы\n"
    "/link КОД — привязать аккаунт (код из Desktop → Настройки → Telegram)"
)


class AddTask(StatesGroup):
    waiting_title = State()
    waiting_ai = State()


def set_hub(hub: HubClient) -> None:
    global _hub
    _hub = hub


def hub() -> HubClient:
    if _hub is None:
        raise RuntimeError("HubClient не инициализирован")
    return _hub


async def _safe(call: Callable[[], Awaitable[Any]]) -> Any | tuple[None, str]:
    """Вызов HUB с человекочитаемой ошибкой (без утечки деталей в чат)."""
    try:
        return await call()
    except HubError as exc:
        if exc.status == 403:
            return None, ("🔒 Аккаунт не привязан. Desktop → Настройки → Telegram → код, "
                          "затем /link КОД")
        return None, f"⚠️ {exc}"


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("link"))
async def cmd_link(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /link КОД (код создаётся в Desktop → Настройки → Telegram)")
        return
    try:
        await hub().link(parts[1].strip(), message.from_user.id,
                         message.from_user.username or "")
        await message.answer("✅ Telegram привязан к F.E.D.O. Personal Edition.",
                             reply_markup=main_menu())
    except HubError as exc:
        await message.answer(f"⚠️ Не удалось привязать: {exc}")
    finally:
        parts[1] = ""  # код не остаётся в памяти/логах


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    result = await _safe(lambda: hub().today(message.from_user.id))
    if isinstance(result, tuple):
        await message.answer(result[1]); return
    await message.answer(fmt.format_today(result), reply_markup=main_menu())


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message) -> None:
    schedule = await _safe(lambda: hub().schedule(message.from_user.id, "tomorrow"))
    if isinstance(schedule, tuple):
        await message.answer(schedule[1]); return
    task_list = await _safe(lambda: hub().tasks(message.from_user.id))
    tasks_text = ""
    if not isinstance(task_list, tuple):
        due_tomorrow = [t for t in (task_list.get("tasks") or [])
                        if (t.get("due_at") or "").startswith(_tomorrow_date())]
        if due_tomorrow:
            tasks_text = "\n\n<b>Задачи на завтра</b>\n" + "\n".join(
                fmt.format_task(t) for t in due_tomorrow[:10])
    await message.answer(fmt.format_schedule(schedule, "Завтра") + tasks_text,
                         reply_markup=main_menu())


def _tomorrow_date() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()


@router.message(Command("tasks"))
async def cmd_tasks(message: Message) -> None:
    result = await _safe(lambda: hub().tasks(message.from_user.id))
    if isinstance(result, tuple):
        await message.answer(result[1]); return
    tasks = result.get("tasks") or []
    if not tasks:
        await message.answer("Задач нет.", reply_markup=main_menu()); return
    await message.answer("<b>Задачи</b>\n" + "\n".join(fmt.format_task(t) for t in tasks[:15]),
                         reply_markup=main_menu())
    for task in tasks[:5]:
        await message.answer(f"⚙️ {fmt.escape_html(task['title'])}",
                             reply_markup=task_actions(task["id"], task["status"]))


@router.message(Command("schedule"))
async def cmd_schedule(message: Message) -> None:
    results = []
    for day, title in (("today", "Сегодня"), ("tomorrow", "Завтра")):
        result = await _safe(lambda d=day: hub().schedule(message.from_user.id, d))
        if isinstance(result, tuple):
            await message.answer(result[1]); return
        results.append(fmt.format_schedule(result, title))
    await message.answer("\n\n".join(results), reply_markup=main_menu())


@router.message(Command("devices"))
async def cmd_devices(message: Message) -> None:
    result = await _safe(lambda: hub().devices(message.from_user.id))
    if isinstance(result, tuple):
        await message.answer(result[1]); return
    await message.answer(fmt.format_devices(result),
                         reply_markup=devices_menu(result.get("devices") or []))


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    result = await _safe(lambda: hub().status(message.from_user.id))
    if isinstance(result, tuple):
        await message.answer(result[1]); return
    await message.answer(fmt.format_status(result), reply_markup=main_menu())


@router.message(Command("ai"))
async def cmd_ai(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await state.set_state(AddTask.waiting_ai)
        await message.answer("О чём спросить F.E.D.O.?")
        return
    await _answer_ai(message, parts[1])


@router.message(AddTask.waiting_ai)
async def ai_question(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _answer_ai(message, message.text or "")


async def _answer_ai(message: Message, question: str) -> None:
    result = await _safe(lambda: hub().ask_ai(message.from_user.id, question))
    if isinstance(result, tuple):
        await message.answer(result[1]); return
    provider = result.get("provider") or "?"
    cloud = "☁️ облако" if result.get("cloud") else "💻 локально"
    await message.answer(f"{fmt.escape_html(result.get('text', ''))}\n\n<i>{provider} · {cloud}</i>",
                         reply_markup=main_menu())


@router.message(AddTask.waiting_title)
async def add_task_title(message: Message, state: FSMContext) -> None:
    await state.clear()
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название пустое — задача не создана.")
        return
    result = await _safe(lambda: hub().create_task(message.from_user.id, title))
    if isinstance(result, tuple):
        await message.answer(result[1]); return
    await message.answer(f"✅ Задача создана: {fmt.escape_html(result['title'])}",
                         reply_markup=task_actions(result["id"], result["status"]))


@router.callback_query(F.data == "menu:main")
async def cb_main(call: CallbackQuery) -> None:
    await call.message.edit_text(HELP_TEXT, reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:today")
async def cb_today(call: CallbackQuery) -> None:
    result = await _safe(lambda: hub().today(call.from_user.id))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    await call.message.edit_text(fmt.format_today(result), reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:tomorrow")
async def cb_tomorrow(call: CallbackQuery) -> None:
    result = await _safe(lambda: hub().schedule(call.from_user.id, "tomorrow"))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    await call.message.edit_text(fmt.format_schedule(result, "Завтра"), reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:tasks")
async def cb_tasks(call: CallbackQuery) -> None:
    result = await _safe(lambda: hub().tasks(call.from_user.id))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    tasks = result.get("tasks") or []
    text = "<b>Задачи</b>\n" + ("\n".join(fmt.format_task(t) for t in tasks[:15]) or "— пусто")
    await call.message.edit_text(text, reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:schedule")
async def cb_schedule(call: CallbackQuery) -> None:
    result = await _safe(lambda: hub().schedule(call.from_user.id, "today"))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    await call.message.edit_text(fmt.format_schedule(result, "Сегодня"), reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:devices")
async def cb_devices(call: CallbackQuery) -> None:
    result = await _safe(lambda: hub().devices(call.from_user.id))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    await call.message.edit_text(fmt.format_devices(result),
                                 reply_markup=devices_menu(result.get("devices") or []))
    await call.answer()


@router.callback_query(F.data == "menu:status")
async def cb_status(call: CallbackQuery) -> None:
    result = await _safe(lambda: hub().status(call.from_user.id))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    await call.message.edit_text(fmt.format_status(result), reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:refresh")
async def cb_refresh(call: CallbackQuery) -> None:
    result = await _safe(lambda: hub().status(call.from_user.id))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    await call.message.edit_text(fmt.format_status(result), reply_markup=main_menu())
    await call.answer("Обновлено")


@router.callback_query(F.data == "menu:checkpc")
async def cb_check_pc(call: CallbackQuery) -> None:
    """Проверить компьютер: статус всех устройств и статистика доступных."""
    result = await _safe(lambda: hub().devices(call.from_user.id))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    devices = result.get("devices") or []
    await call.message.edit_text(fmt.format_devices(result),
                                 reply_markup=devices_menu(devices))
    await call.answer("Проверено")
    for device in devices[:2]:
        if device.get("status") != "online":
            continue
        await _safe(lambda d=device: hub().device_command(
            call.from_user.id, d["id"], "stats"))


@router.callback_query(F.data == "menu:add")
async def cb_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddTask.waiting_title)
    await call.message.answer("Название задачи?")
    await call.answer()


@router.callback_query(F.data == "menu:ai")
async def cb_ai(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddTask.waiting_ai)
    await call.message.answer("О чём спросить F.E.D.O.?")
    await call.answer()


@router.callback_query(F.data.startswith("task:"))
async def cb_task(call: CallbackQuery) -> None:
    _, action, task_id = call.data.split(":", 2)
    result = await _safe(lambda: hub().task_action(call.from_user.id, task_id,
                                                  action, 15 if action == "extend" else 0))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    await call.message.edit_text(f"Обновлено: {fmt.format_task(result)}",
                                 reply_markup=task_actions(result["id"], result["status"]))
    await call.answer("Готово")


@router.callback_query(F.data.startswith("device:"))
async def cb_device(call: CallbackQuery) -> None:
    _, action, device_id = call.data.split(":", 2)
    result = await _safe(lambda: hub().device_command(call.from_user.id, device_id, action))
    if isinstance(result, tuple):
        await call.answer(result[1], show_alert=True); return
    if result.get("requires_confirmation"):
        await call.answer("Требуется подтверждение в Desktop", show_alert=True)
        await call.message.answer("🔐 Опасное действие отправлено на подтверждение в Desktop.")
    else:
        await call.answer("Команда отправлена")


@router.message()
async def fallback(message: Message) -> None:
    """Любой свободный текст — вопрос к AI (как в Desktop)."""
    await _answer_ai(message, message.text or "")


async def reminder_loop(bot: Bot, client: HubClient, interval: int = 60) -> None:
    """Напоминания: опрос HUB, отправка без дублей."""
    while True:
        try:
            for telegram_id in await _known_telegram_ids(bot, client):
                data = await client.reminders(telegram_id)
                for item in data.get("reminders", []):
                    task_id = (item.get("task") or {}).get("id", "")
                    key = f"{telegram_id}:{task_id}:{item.get('at')}"
                    if key in _notified:
                        continue
                    _notified.add(key)
                    try:
                        await bot.send_message(telegram_id, fmt.format_reminder(item),
                                               reply_markup=main_menu())
                    except Exception:
                        continue
        except Exception as exc:  # цикл не должен падать
            logger.warning("reminder loop: %s", exc)
        await asyncio.sleep(interval)


async def _known_telegram_ids(bot: Bot, client: HubClient) -> list[int]:
    """Список привязанных ID ведёт HUB; бот запрашивает его служебно."""
    try:
        data = await client.accounts()
        return [int(row["telegram_id"]) for row in data.get("accounts", [])]
    except HubError:
        return []


async def run() -> None:
    token = os.environ.get("FEDO_TELEGRAM_BOT_TOKEN", "")
    hub_url = os.environ.get("FEDO_HUB_URL", "")
    service_token = os.environ.get("FEDO_BOT_SERVICE_TOKEN", "")
    if not token or not hub_url or not service_token:
        raise SystemExit("Нужны FEDO_TELEGRAM_BOT_TOKEN, FEDO_HUB_URL, FEDO_BOT_SERVICE_TOKEN")
    logging.basicConfig(level=logging.INFO)
    client = HubClient(hub_url, service_token)
    set_hub(client)
    bot = Bot(token, default=DefaultBotProperties(parse_mode="HTML"))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    asyncio.create_task(reminder_loop(bot, client))
    logger.info("F.E.D.O. Mini запущен")
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    asyncio.run(run())
