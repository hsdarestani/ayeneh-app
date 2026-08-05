from __future__ import annotations

from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.config import get_settings
from app.content import RELATIONS, SCORE_LABELS
from app.payments import payment_signature

settings = get_settings()


MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🪞 ساخت آینه من")],
        [KeyboardButton(text="🎁 نمونه گزارش کامل")],
        [KeyboardButton(text="📊 آینه‌های من"), KeyboardButton(text="💡 آینه چطور کار می‌کنه؟")],
    ],
    resize_keyboard=True,
    input_field_placeholder="از کجا شروع کنیم؟ 👇",
)


SCORE_EMOJIS = {
    1: "🚫",
    2: "🤏",
    3: "😐",
    4: "🙂",
    5: "🔥",
}

RELATION_EMOJIS = {
    "friend": "👫",
    "family": "🏠",
    "coworker": "🎓",
    "other": "🙂",
}


def score_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{SCORE_EMOJIS[value]} {SCORE_LABELS[value]}",
                    callback_data=f"score:{value}",
                )
            ]
            for value in range(5, 0, -1)
        ]
    )


def relation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{RELATION_EMOJIS.get(key, '•')} {label}",
                    callback_data=f"relation:{key}",
                )
            ]
            for key, label in RELATIONS.items()
        ]
    )


def mirror_keyboard(mirror_id: int, paid: bool, can_preview: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="📤 فرستادن لینک برای دوست‌ها", callback_data=f"invite:{mirror_id}")]]
    if can_preview:
        rows.append([InlineKeyboardButton(text="👀 دیدن پیش‌نمایش رایگان", callback_data=f"preview:{mirror_id}")])
    if paid:
        rows.append([InlineKeyboardButton(text="📖 دیدن گزارش کامل من", callback_data=f"report:{mirror_id}")])
    else:
        signature = payment_signature(settings, mirror_id)
        payment_url = f"{settings.public_base_url}/payment/start/{mirror_id}?sig={signature}"
        rows.append([InlineKeyboardButton(text="🎁 اول نمونه گزارش را ببین", callback_data=f"sample:{mirror_id}")])
        rows.append([InlineKeyboardButton(text="💳 پرداخت و باز کردن گزارش کامل", url=payment_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def share_keyboard(invite_link: str, owner_name: str) -> InlineKeyboardMarkup:
    # The URL is passed separately to Telegram. Do not repeat it inside text,
    # otherwise the shared message contains the same link twice.
    text = (
        f"🪞 {owner_name} می‌خواد بدونه از نگاه تو چه‌جور آدمیه!\n\n"
        f"فقط ۸ سؤال کوتاهه و جواب‌هات برای {owner_name} کاملاً ناشناس می‌مونه 🤫\n"
        "صادقانه جواب بده 👇"
    )
    share_url = f"https://t.me/share/url?url={quote(invite_link)}&text={quote(text)}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 انتخاب دوست و ارسال لینک", url=share_url)],
            [InlineKeyboardButton(text="🪞 تست کردن لینک خودم", url=invite_link)],
        ]
    )


def receipt_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    # Kept only for legacy receipt messages that may still exist in Telegram.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید پرداخت", callback_data=f"payment:approve:{payment_id}"),
                InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"payment:reject:{payment_id}"),
            ]
        ]
    )
