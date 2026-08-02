from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.cards import make_result_card
from app.config import get_settings
from app.content import RELATIONS, TRAITS
from app.database import init_db
from app.keyboards import MAIN_MENU, mirror_keyboard, receipt_keyboard, relation_keyboard, score_keyboard, share_keyboard
from app.presentation import demo_report_text, demo_stats, preview_text
from app.services import admin_stats, create_mirror, create_payment, generate_report, get_mirror, get_mirror_by_token, get_stats, has_responded, list_user_mirrors, review_payment, save_answers, store_report, upsert_user
from app.states import FriendSurvey, PaymentFlow, SelfSurvey
from app.web import make_web_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ayeneh")
settings = get_settings()
router = Router()
bot_username = ""


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_telegram_ids


def progress(index: int) -> str:
    return f"{'●' * (index + 1)}{'○' * (len(TRAITS) - index - 1)}"


async def send_question(message: Message, *, index: int, is_self: bool, edit: bool = False) -> None:
    trait = TRAITS[index]
    question = trait.self_question if is_self else trait.other_question
    text = (
        f"🪞 <b>سؤال {index + 1} از {len(TRAITS)}</b>\n"
        f"{progress(index)}\n\n"
        f"{question}\n\n"
        "کدوم گزینه بیشتر به حست نزدیکه؟ 👇"
    )
    if edit:
        await message.edit_text(text, reply_markup=score_keyboard())
    else:
        await message.answer(text, reply_markup=score_keyboard())


async def ensure_user(message: Message):
    assert message.from_user is not None
    return await upsert_user(message.from_user.id, message.from_user.first_name, message.from_user.username)


async def send_demo_report(message: Message) -> None:
    try:
        card = make_result_card("سارا (نمونه)", demo_stats())
        await message.answer_photo(
            BufferedInputFile(card, filename="ayeneh-sample.png"),
            caption=(
                "🖼 <b>نمونه کارت تصویری آینه</b>\n"
                "این کارت همراه گزارش کامل ساخته می‌شه و آماده اشتراک‌گذاریه."
            ),
        )
    except Exception:
        logger.exception("Could not create demo result card")
    await message.answer(demo_report_text(), reply_markup=MAIN_MENU)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await ensure_user(message)
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    if payload.startswith("mirror_"):
        token = payload.removeprefix("mirror_")
        mirror = await get_mirror_by_token(token)
        if mirror is None or not mirror.self_completed:
            await message.answer(
                "⚠️ این لینک معتبر نیست یا صاحب آینه هنوز سؤال‌های خودش را کامل نکرده.",
                reply_markup=MAIN_MENU,
            )
            return

        if mirror.owner.telegram_id == message.from_user.id:
            stats = await get_stats(mirror.id)
            remaining = max(0, settings.min_responses_for_preview - stats.respondent_count)
            if remaining:
                status = f"برای پیش‌نمایش فقط <b>{remaining}</b> پاسخ دیگه لازمه."
            else:
                status = "🎉 پیش‌نمایش رایگان نتیجه‌ات آماده‌ست!"
            await message.answer(
                "🪞 <b>این لینک مربوط به آینه خودته</b>\n\n"
                f"👥 تا الان <b>{stats.respondent_count}</b> نفر جواب داده‌اند.\n"
                f"{status}",
                reply_markup=mirror_keyboard(
                    mirror.id,
                    mirror.paid,
                    stats.respondent_count >= settings.min_responses_for_preview,
                ),
            )
            return

        if await has_responded(mirror.id, message.from_user.id):
            await message.answer(
                f"✅ جواب تو قبلاً برای آینه <b>{mirror.owner.first_name}</b> ثبت شده.\n\n"
                "ممنون که صادقانه کمک کردی 🤍\n"
                "حالا کنجکاوی بدونی بقیه تو را چطور می‌بینن؟ 😏",
                reply_markup=MAIN_MENU,
            )
            return

        await state.set_state(FriendSurvey.choosing_relation)
        await state.update_data(mirror_id=mirror.id, owner_name=mirror.owner.first_name)
        await message.answer(
            f"👋 <b>{mirror.owner.first_name}</b> ازت خواسته کمکش کنی خودش را از نگاه بقیه ببینه.\n\n"
            "فقط <b>۸ سؤال کوتاه</b>ه و حدود یک دقیقه زمان می‌بره ⏱\n\n"
            f"🤫 اسم و انتخاب‌های تو به {mirror.owner.first_name} نمایش داده نمی‌شه.\n"
            "📊 فقط میانگین همه جواب‌ها وارد گزارش می‌شه.\n\n"
            "اول بگو از کجا همدیگه را می‌شناسین 👇",
            reply_markup=relation_keyboard(),
        )
        return

    await message.answer(
        "🪞 <b>آدم‌هایی که می‌شناسنت، واقعاً چه تصویری از تو دارن؟</b>\n\n"
        "اول خودت به ۸ سؤال کوتاه جواب می‌دی؛ بعد لینک مخصوصت را برای دوستات می‌فرستی. جواب‌ها برای تو ناشناس جمع می‌شن و آینه نشونت می‌ده:\n\n"
        "✨ کدوم ویژگی‌هات بیشتر به چشم میاد\n"
        "👀 کجا خودت را متفاوت از بقیه می‌بینی\n"
        "💡 چه چیزی شاید درباره خودت نمی‌دیدی\n\n"
        "شروعش کمتر از دو دقیقه‌ست 👇",
        reply_markup=MAIN_MENU,
    )


@router.message(F.text == "💡 آینه چطور کار می‌کنه؟")
async def about(message: Message) -> None:
    await message.answer(
        "💡 <b>آینه چطور کار می‌کنه؟</b>\n\n"
        "1️⃣ تو به ۸ سؤال ساده درباره خودت جواب می‌دی.\n"
        "2️⃣ یک لینک خصوصی می‌گیری و برای دوستات می‌فرستی.\n"
        "3️⃣ دوستات همان سؤال‌ها را درباره تو جواب می‌دن.\n"
        "4️⃣ بعد از ۳ پاسخ، یک پیش‌نمایش رایگان می‌بینی.\n"
        "5️⃣ در گزارش کامل، نگاه خودت با نگاه بقیه در هر ۸ ویژگی مقایسه می‌شه.\n\n"
        "🤫 جواب هر نفر برای صاحب آینه ناشناسه؛ اسم یا پاسخ تکی کسی نمایش داده نمی‌شه.\n"
        "🎁 قبل از پرداخت هم می‌تونی نمونه گزارش کامل را ببینی.\n\n"
        "آینه تشخیص روان‌شناسی نیست؛ یک تصویر جمعی و سرگرم‌کننده از نگاه آدم‌های اطرافته.",
        reply_markup=MAIN_MENU,
    )


@router.message(F.text == "🎁 نمونه گزارش کامل")
async def sample_report_message(message: Message) -> None:
    await send_demo_report(message)


@router.message(F.text == "🪞 ساخت آینه من")
async def begin_self_survey(message: Message, state: FSMContext) -> None:
    user = await ensure_user(message)
    mirror = await create_mirror(user.id)
    await state.set_state(SelfSurvey.answering)
    await state.update_data(mirror_id=mirror.id, index=0, scores={})
    await message.answer(
        "بزن بریم! 🪞\n\n"
        "فقط ۸ سؤال کوتاهه. با حسی که همین الان نسبت به خودت داری جواب بده و زیاد فکرش نکن.\n\n"
        "اینجا جواب درست یا غلط نداریم 🤍"
    )
    await send_question(message, index=0, is_self=True)


@router.callback_query(FriendSurvey.choosing_relation, F.data.startswith("relation:"))
async def choose_relation(callback: CallbackQuery, state: FSMContext) -> None:
    relation = callback.data.split(":", 1)[1]
    if relation not in RELATIONS:
        await callback.answer("این گزینه معتبر نیست.", show_alert=True)
        return
    await state.set_state(FriendSurvey.answering)
    await state.update_data(relation=relation, index=0, scores={})
    await callback.answer()
    assert callback.message is not None
    await callback.message.edit_text(
        "عالیه، شروع کنیم 🙌\n\n"
        "همون حسی را انتخاب کن که واقعاً از این آدم داری؛ نه چیزی که فکر می‌کنی دوست داره بشنوه.\n\n"
        "🤫 صاحب آینه هیچ‌وقت نمی‌فهمه تو برای هر سؤال چه گزینه‌ای زدی."
    )
    await send_question(callback.message, index=0, is_self=False)


@router.callback_query(SelfSurvey.answering, F.data.startswith("score:"))
async def self_score(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await handle_score(callback, state, bot, is_self=True)


@router.callback_query(FriendSurvey.answering, F.data.startswith("score:"))
async def friend_score(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await handle_score(callback, state, bot, is_self=False)


async def handle_score(callback: CallbackQuery, state: FSMContext, bot: Bot, *, is_self: bool) -> None:
    assert callback.from_user is not None and callback.message is not None
    try:
        value = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("این امتیاز معتبر نیست.", show_alert=True)
        return
    if value not in range(1, 6):
        await callback.answer("این امتیاز معتبر نیست.", show_alert=True)
        return

    data = await state.get_data()
    index = int(data.get("index", 0))
    scores = dict(data.get("scores", {}))
    scores[TRAITS[index].key] = value
    next_index = index + 1
    await callback.answer()

    if next_index < len(TRAITS):
        await state.update_data(index=next_index, scores=scores)
        await send_question(callback.message, index=next_index, is_self=is_self, edit=True)
        return

    mirror_id = int(data["mirror_id"])
    relation = None if is_self else str(data.get("relation", "other"))
    await save_answers(mirror_id, callback.from_user.id, scores, is_self=is_self, relation=relation)
    await state.clear()

    if is_self:
        mirror = await get_mirror(mirror_id)
        assert mirror is not None
        invite_link = f"https://t.me/{bot_username}?start=mirror_{mirror.token}"
        await callback.message.edit_text(
            "🎉 <b>آینه‌ات ساخته شد!</b>\n\n"
            "حالا باید چند نفر که واقعاً می‌شناسنت به سؤال‌ها جواب بدن.\n\n"
            "👥 برای شروع لینک را برای حداقل ۳ نفر بفرست.\n"
            "🎯 با ۵ نفر به بالا، نتیجه دقیق‌تر و جالب‌تر می‌شه.\n"
            "🤫 جواب هر نفر برای تو ناشناس می‌مونه.\n"
            "👀 بعد از ۳ پاسخ، اولین نتیجه رایگان باز می‌شه.\n\n"
            "از دکمه زیر دوستات را انتخاب کن 👇",
            reply_markup=share_keyboard(invite_link, mirror.owner.first_name),
        )
    else:
        mirror = await get_mirror(mirror_id)
        assert mirror is not None
        stats = await get_stats(mirror_id)
        await callback.message.edit_text(
            "✅ <b>تموم شد!</b>\n\n"
            "جواب‌هات ناشناس ثبت شد. صاحب آینه فقط نتیجه جمعی را می‌بینه؛ نه اسم تو و نه انتخاب‌هات 🤫\n\n"
            "ممنون که صادقانه کمک کردی 🤍"
        )
        await callback.message.answer(
            "حالا کنجکاوی بدونی بقیه تو را چطور می‌بینن؟ 😏\nآینه خودت را بساز 👇",
            reply_markup=MAIN_MENU,
        )
        with suppress(Exception):
            remaining = max(0, settings.min_responses_for_preview - stats.respondent_count)
            note = (
                "🔔 <b>یک نفر تازه به آینه‌ات جواب داد!</b>\n\n"
                f"👥 تعداد پاسخ‌ها: <b>{stats.respondent_count}</b>"
            )
            if remaining > 0:
                note += f"\n⏳ فقط <b>{remaining}</b> پاسخ دیگه تا پیش‌نمایش رایگان."
            elif stats.respondent_count == settings.min_responses_for_preview:
                note += "\n\n🎉 پیش‌نمایش رایگان نتیجه‌ات آماده شد! از بخش «آینه‌های من» ببینش."
            await bot.send_message(mirror.owner.telegram_id, note, reply_markup=MAIN_MENU)


@router.message(F.text == "📊 آینه‌های من")
async def my_mirrors(message: Message) -> None:
    user = await ensure_user(message)
    mirrors = await list_user_mirrors(user.id)
    if not mirrors:
        await message.answer(
            "هنوز آینه‌ای نساختی 🪞\n\nاول آینه خودت را بساز و لینکش را برای دوستات بفرست.",
            reply_markup=MAIN_MENU,
        )
        return

    await message.answer("📊 <b>آینه‌های تو</b>\nآخرین آینه‌ها و وضعیت نتیجه‌ها:")
    for mirror in mirrors:
        stats = await get_stats(mirror.id)
        can_preview = stats.respondent_count >= settings.min_responses_for_preview
        if can_preview:
            preview_status = "آماده‌ست ✅"
        else:
            remaining = settings.min_responses_for_preview - stats.respondent_count
            preview_status = f"{remaining} پاسخ دیگه می‌خواد ⏳"
        report_status = "باز شده 🔓" if mirror.paid else "هنوز قفله 🔒"
        await message.answer(
            f"🪞 <b>آینه #{mirror.id}</b>\n"
            f"👥 پاسخ‌ها: <b>{stats.respondent_count} نفر</b>\n"
            f"👀 پیش‌نمایش: {preview_status}\n"
            f"📖 گزارش کامل: {report_status}",
            reply_markup=mirror_keyboard(mirror.id, mirror.paid, can_preview),
        )


async def owned_mirror(callback: CallbackQuery, mirror_id: int):
    mirror = await get_mirror(mirror_id)
    if mirror is None or callback.from_user is None or mirror.owner.telegram_id != callback.from_user.id:
        await callback.answer("این آینه برای حساب تو نیست.", show_alert=True)
        return None
    return mirror


@router.callback_query(F.data.startswith("invite:"))
async def invite(callback: CallbackQuery) -> None:
    mirror_id = int(callback.data.split(":", 1)[1])
    mirror = await owned_mirror(callback, mirror_id)
    if mirror is None:
        return
    invite_link = f"https://t.me/{bot_username}?start=mirror_{mirror.token}"
    await callback.answer()
    assert callback.message is not None
    await callback.message.answer(
        "📤 <b>لینک اختصاصی آینه‌ات آماده‌ست</b>\n\n"
        "با دکمه زیر دوستات را انتخاب کن؛ متن دعوت و لینک خودکار براشون فرستاده می‌شه.\n\n"
        "🎯 پیشنهاد: برای ۵ تا ۱۰ نفر که واقعاً می‌شناسنت بفرست تا نتیجه جذاب‌تر بشه.",
        reply_markup=share_keyboard(invite_link, mirror.owner.first_name),
    )


@router.callback_query(F.data.startswith("sample:"))
async def sample_report_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    assert callback.message is not None
    await send_demo_report(callback.message)


@router.callback_query(F.data.startswith("preview:"))
async def preview(callback: CallbackQuery) -> None:
    mirror_id = int(callback.data.split(":", 1)[1])
    mirror = await owned_mirror(callback, mirror_id)
    if mirror is None:
        return
    stats = await get_stats(mirror_id)
    if stats.respondent_count < settings.min_responses_for_preview:
        remaining = settings.min_responses_for_preview - stats.respondent_count
        await callback.answer(f"هنوز {remaining} پاسخ دیگه برای پیش‌نمایش لازمه.", show_alert=True)
        return
    await callback.answer()
    assert callback.message is not None
    await callback.message.answer(
        preview_text(stats),
        reply_markup=mirror_keyboard(mirror.id, mirror.paid, True),
    )


@router.callback_query(F.data.startswith("pay:"))
async def pay(callback: CallbackQuery, state: FSMContext) -> None:
    mirror_id = int(callback.data.split(":", 1)[1])
    mirror = await owned_mirror(callback, mirror_id)
    if mirror is None:
        return
    if mirror.paid:
        await callback.answer("گزارش کاملت قبلاً باز شده ✅")
        return
    if not settings.card_number or not settings.card_holder:
        await callback.answer("اطلاعات پرداخت هنوز تنظیم نشده. کمی بعد دوباره امتحان کن.", show_alert=True)
        return

    await state.set_state(PaymentFlow.waiting_receipt)
    await state.update_data(mirror_id=mirror_id)
    await callback.answer()
    assert callback.message is not None
    await callback.message.answer(
        "🔓 <b>با باز کردن گزارش کامل چه می‌گیری؟</b>\n\n"
        "🪞 جمع‌بندی شخصی‌سازی‌شده از نگاه اطرافیانت\n"
        "✨ سه ویژگی پررنگت با توضیح\n"
        "👀 بزرگ‌ترین تفاوت نگاه خودت و بقیه\n"
        "📊 مقایسه کامل هر ۸ ویژگی\n"
        "💡 یک پیشنهاد کاربردی متناسب با نتیجه تو\n"
        "🖼 کارت تصویری آماده استوری\n\n"
        f"💳 مبلغ: <b>{settings.price_label} تومان</b>\n\n"
        f"<code>{settings.card_display}</code>\n"
        f"به نام <b>{settings.card_holder}</b>\n\n"
        "بعد از کارت‌به‌کارت، عکس رسید را همین‌جا بفرست 📸\n"
        "پرداخت به‌صورت دستی بررسی می‌شه و بعد گزارش همین‌جا باز می‌شه.",
    )


@router.message(PaymentFlow.waiting_receipt, F.photo)
async def receipt_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    await register_receipt(message, state, bot, message.photo[-1].file_id, "photo")


@router.message(PaymentFlow.waiting_receipt, F.document)
async def receipt_document(message: Message, state: FSMContext, bot: Bot) -> None:
    document = message.document
    if document is None or (document.mime_type or "").lower() not in {"image/jpeg", "image/png", "image/webp"}:
        await message.answer("📸 لطفاً تصویر رسید را به‌صورت عکس یا فایل JPG/PNG بفرست.")
        return
    await register_receipt(message, state, bot, document.file_id, "document")


@router.message(PaymentFlow.waiting_receipt)
async def receipt_invalid(message: Message) -> None:
    await message.answer("منتظر عکس رسید پرداخت هستم 📸")


async def register_receipt(message: Message, state: FSMContext, bot: Bot, file_id: str, kind: str) -> None:
    assert message.from_user is not None
    data = await state.get_data()
    mirror_id = int(data["mirror_id"])
    mirror = await get_mirror(mirror_id)
    if mirror is None or mirror.owner.telegram_id != message.from_user.id:
        await state.clear()
        await message.answer("⚠️ آینه پیدا نشد. دوباره از بخش «آینه‌های من» وارد شو.")
        return

    payment = await create_payment(mirror_id, message.from_user.id, file_id, kind)
    await state.clear()
    await message.answer(
        "✅ <b>رسیدت ثبت شد</b>\n\n"
        "بعد از بررسی، نتیجه همین‌جا بهت اعلام می‌شه و گزارش کاملت باز می‌شه 🪞",
        reply_markup=MAIN_MENU,
    )

    caption = (
        "💳 <b>رسید جدید آینه</b>\n"
        f"پرداخت #{payment.id}\n"
        f"آینه #{mirror_id}\n"
        f"کاربر: <code>{message.from_user.id}</code>"
    )
    if not settings.admin_telegram_ids:
        logger.warning("Payment %s submitted but ADMIN_TELEGRAM_IDS is empty", payment.id)
        return
    for admin_id in settings.admin_telegram_ids:
        with suppress(Exception):
            if kind == "photo":
                await bot.send_photo(admin_id, file_id, caption=caption, reply_markup=receipt_keyboard(payment.id))
            else:
                await bot.send_document(admin_id, file_id, caption=caption, reply_markup=receipt_keyboard(payment.id))


@router.callback_query(F.data.startswith("payment:"))
async def payment_review(callback: CallbackQuery, bot: Bot) -> None:
    assert callback.from_user is not None
    if not is_admin(callback.from_user.id):
        await callback.answer("این دکمه فقط برای ادمینه.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("درخواست معتبر نیست.", show_alert=True)
        return
    action, payment_id_raw = parts[1], parts[2]
    approve = action == "approve"
    if action not in {"approve", "reject"}:
        await callback.answer("درخواست معتبر نیست.", show_alert=True)
        return

    payment, mirror = await review_payment(int(payment_id_raw), callback.from_user.id, approve)
    if payment is None or (mirror is None and approve):
        await callback.answer("این رسید قبلاً بررسی شده یا پیدا نشد.", show_alert=True)
        return

    await callback.answer("پرداخت تأیید شد ✅" if approve else "پرداخت رد شد ❌")
    assert callback.message is not None
    status = "✅ تأیید شد" if approve else "❌ رد شد"
    with suppress(Exception):
        await callback.message.edit_caption(caption=f"{callback.message.caption or ''}\n\n{status}")

    if approve and mirror:
        await bot.send_message(
            payment.payer_telegram_id,
            "🎉 <b>پرداختت تأیید شد!</b>\n\n"
            "گزارش کامل آینه‌ات باز شده. روی دکمه زیر بزن و نتیجه‌ات را ببین 👇",
            reply_markup=mirror_keyboard(mirror.id, True, True),
        )
    else:
        await bot.send_message(
            payment.payer_telegram_id,
            "❌ رسید پرداخت تأیید نشد.\n\n"
            "ممکنه عکس رسید ناخوانا بوده یا اطلاعات پرداخت درست نباشه. از بخش «آینه‌های من» دوباره وارد گزارش کامل شو و رسید درست را بفرست.",
            reply_markup=MAIN_MENU,
        )


@router.callback_query(F.data.startswith("report:"))
async def report(callback: CallbackQuery) -> None:
    mirror_id = int(callback.data.split(":", 1)[1])
    mirror = await owned_mirror(callback, mirror_id)
    if mirror is None:
        return
    if not mirror.paid:
        await callback.answer("اول باید پرداختت تأیید بشه.", show_alert=True)
        return

    stats = await get_stats(mirror.id)
    if stats.respondent_count < settings.min_responses_for_preview:
        remaining = settings.min_responses_for_preview - stats.respondent_count
        await callback.answer(f"هنوز {remaining} پاسخ دیگه برای گزارش لازمه.", show_alert=True)
        return

    await callback.answer("گزارش شخصی تو داره آماده می‌شه… 🪞")
    assert callback.message is not None
    await callback.message.answer(
        f"✨ گزارش کاملت بر اساس <b>{stats.respondent_count} پاسخ ناشناس</b> آماده شد:"
    )

    report_text = mirror.report_text
    if not report_text:
        report_text = await generate_report(settings, mirror.owner.first_name, stats)
        await store_report(mirror.id, report_text)
    await callback.message.answer(report_text)

    try:
        card = make_result_card(mirror.owner.first_name, stats)
        await callback.message.answer_photo(
            BufferedInputFile(card, filename=f"ayeneh-{mirror.id}.png"),
            caption=(
                "🖼 <b>کارت تصویری آینه تو</b>\n"
                "می‌تونی ذخیره‌اش کنی و برای استوری یا دوستات بفرستی 🪞"
            ),
        )
    except Exception:
        logger.exception("Could not create result card for mirror %s", mirror.id)


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    assert message.from_user is not None
    if not is_admin(message.from_user.id):
        return
    values = await admin_stats()
    await message.answer(
        "📊 <b>آمار آینه</b>\n\n"
        f"👤 کاربرها: {values['users']}\n"
        f"🪞 آینه‌ها: {values['mirrors']}\n"
        f"👥 پاسخ‌دهنده‌ها: {values['responses']}\n"
        f"⏳ پرداخت‌های در انتظار: {values['pending']}\n"
        f"🔓 گزارش‌های بازشده: {values['paid']}"
    )


@router.message(Command("id"))
async def id_command(message: Message) -> None:
    assert message.from_user is not None
    await message.answer(f"🆔 شناسه عددی تلگرام شما:\n<code>{message.from_user.id}</code>")


@router.message(F.text.casefold() == "حذف اطلاعات من")
async def delete_data_info(message: Message) -> None:
    await message.answer(
        "برای حذف اطلاعات، شناسه‌ات را با دستور /id بگیر و برای پشتیبانی پروژه ارسال کن. امکان حذف مستقیم از داخل ربات هم در نسخه بعد اضافه می‌شه."
    )


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(
        "متوجه نشدم کدوم بخش را می‌خوای 😅\nاز دکمه‌های پایین یکی را انتخاب کن 👇",
        reply_markup=MAIN_MENU,
    )


async def run_web(bot: Bot) -> web.AppRunner:
    app = make_web_app(settings, bot_username)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()
    return runner


async def main() -> None:
    global bot_username
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    await init_db()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    bot_username = me.username or ""
    if not bot_username:
        raise RuntimeError("Bot username is required")
    await bot.delete_webhook(drop_pending_updates=False)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    runner = await run_web(bot)
    logger.info("Ayeneh started as @%s", bot_username)
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
