from __future__ import annotations

from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.content import RELATIONS, SCORE_LABELS


MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🪞 ساخت آینه من")],
        [KeyboardButton(text="📊 آینه‌های من"), KeyboardButton(text="✨ آینه چیه؟")],
    ],
    resize_keyboard=True,
    input_field_placeholder="یکی از گزینه‌ها را انتخاب کن…",
)


def score_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{value} · {SCORE_LABELS[value]}", callback_data=f"score:{value}")]
            for value in range(5, 0, -1)
        ]
    )


def relation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"relation:{key}")]
            for key, label in RELATIONS.items()
        ]
    )


def mirror_keyboard(mirror_id: int, paid: bool, can_preview: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔗 لینک دعوت", callback_data=f"invite:{mirror_id}")]]
    if can_preview:
        rows.append([InlineKeyboardButton(text="👀 پیش‌نمایش نتیجه", callback_data=f"preview:{mirror_id}")])
    if paid:
        rows.append([InlineKeyboardButton(text="📖 گزارش کامل", callback_data=f"report:{mirror_id}")])
    else:
        rows.append([InlineKeyboardButton(text="🔓 باز کردن گزارش کامل", callback_data=f"pay:{mirror_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def share_keyboard(invite_link: str, owner_name: str) -> InlineKeyboardMarkup:
    text = f"به آینه من جواب بده؛ ناشناسه و فقط نتیجه جمعی نمایش داده می‌شه 🪞\n{invite_link}"
    share_url = f"https://t.me/share/url?url={quote(invite_link)}&text={quote(text)}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 فرستادن برای دوست‌ها", url=share_url)],
            [InlineKeyboardButton(text="🪞 باز کردن لینک", url=invite_link)],
        ]
    )


def receipt_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید", callback_data=f"payment:approve:{payment_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"payment:reject:{payment_id}"),
            ]
        ]
    )
