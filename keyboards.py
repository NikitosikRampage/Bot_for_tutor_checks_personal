from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить оплату")],
            [KeyboardButton(text="Мои платежи")],
        ],
        resize_keyboard=True
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    )


def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Все платежи"), KeyboardButton(text="Ожидают проверки")],
            [KeyboardButton(text="Отчеты за неделю")],
        ],
        resize_keyboard=True
    )

def get_pending_actions_keyboard(payment_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Подтвердить", callback_data=f"approve_{payment_id}"),
        InlineKeyboardButton(text="Отклонить",   callback_data=f"reject_{payment_id}"),
    )
    return builder.as_markup()


def get_approved_actions_keyboard(payment_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="Удалить", callback_data=f"delete_{payment_id}")
    )
    return builder.as_markup()


def get_week_delete_keyboard(week_start_str: str):
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text="❌ Удалить ВСЕ платежи за эту неделю",
            callback_data=f"weekdel_confirm_{week_start_str}"
        )
    )
    return builder.as_markup()
def get_delete_confirm_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Да, удалить"),
                KeyboardButton(text="Отмена")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )