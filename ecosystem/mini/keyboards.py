"""Клавиатуры бота (inline): навигация и действия с задачами/устройствами."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="menu:today"),
         InlineKeyboardButton(text="➡️ Завтра", callback_data="menu:tomorrow")],
        [InlineKeyboardButton(text="✅ Задачи", callback_data="menu:tasks"),
         InlineKeyboardButton(text="🗓 Расписание", callback_data="menu:schedule")],
        [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="menu:add"),
         InlineKeyboardButton(text="🖥 Статус ПК", callback_data="menu:devices")],
        [InlineKeyboardButton(text="🤖 Спросить AI", callback_data="menu:ai"),
         InlineKeyboardButton(text="📊 Статус", callback_data="menu:status")],
        [InlineKeyboardButton(text="🔍 Проверить компьютер", callback_data="menu:checkpc"),
         InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:refresh")],
    ])


def task_actions(task_id: str, status: str = "todo") -> InlineKeyboardMarkup:
    rows = []
    if status == "todo":
        rows.append([InlineKeyboardButton(text="▶️ Начать", callback_data=f"task:start:{task_id}"),
                     InlineKeyboardButton(text="✅ Завершить", callback_data=f"task:complete:{task_id}")])
    elif status == "in_progress":
        rows.append([InlineKeyboardButton(text="✅ Завершить", callback_data=f"task:complete:{task_id}"),
                     InlineKeyboardButton(text="⏱ +15 минут", callback_data=f"task:extend:{task_id}")])
    else:
        rows.append([InlineKeyboardButton(text="↩️ Вернуть в работу", callback_data=f"task:reopen:{task_id}")])
    rows.append([InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"task:skip:{task_id}"),
                 InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def devices_menu(devices: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for device in devices[:6]:
        rows.append([InlineKeyboardButton(
            text=f"🖥 {device['name']}: статус",
            callback_data=f"device:status:{device['id']}")])
    for device in devices[:3]:
        rows.append([InlineKeyboardButton(
            text=f"🌙 {device['name']}: сон (с подтверждением)",
            callback_data=f"device:sleep:{device['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]])
