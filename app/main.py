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
from app.services import admin_stats, create_mirror, create_payment, generate_report, get_mirror, get_mirror_by_token, get_stats, has_responded, list_user_mirrors, preview_text, review_payment, save_answers, store_report, upsert_user
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
    return f"{'●' * (index + 1)}{'○' * (len(TRAITS) - index - 1)}  {index + 1}/{len(TRAITS)}"


async def send_question(message: Message, *, index: int, is_self: bool, edit: bool = False) -> None:
    trait = TRAITS[index]
    question = trait.self_question if is_self else trait.other_question
    text = f"<b>{progress(index)}</b>\n\n{question}\n\nاز ۱ تا ۵ انتخاب کن:"
    if edit:
        await message.edit_text(text, reply_markup=score_keyboard())
    else:
        await message.answer(text, reply_markup=score_keyboard())


async def ensure_user(message: Message):
    assert message.from_user is not None
    return await upsert_user(message.from_user.id, message.from_user.first_name, message.from_user.username)


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
            await message.answer("این لینک معتبر نیست یا آینه هنوز آماده نشده.", reply_markup=MAIN_MENU)
            return
        if mirror.owner.telegram_id == message.from_user.id:
            stats = await get_stats(mirror.id)
            await message.answer(f"این آینه خودته 🪞\nتا الان <b>{stats.respondent_count}</b> نفر جواب داده‌اند.", reply_markup=mirror_keyboard(mirror.id, mirror.paid, stats.respondent_count >= settings.min_responses_for_preview))
            return
        if await has_responded(mirror.id, message.from_user.id):
            await message.answer(f"جوابت قبلاً برای آینه {mirror.owner.first_name} ثبت شده. ممنون که صادقانه جواب دادی 🤍\n\nحالا می‌تونی آینه خودت را بسازی:", reply_markup=MAIN_MENU)
            return
        await state.set_state(FriendSurvey.choosing_relation)
        await state.update_data(mirror_id=mirror.id, owner_name=mirror.owner.first_name)
        await message.answer(f"<b>{mirror.owner.first_name}</b> می‌خواد خودش را از نگاه آدم‌هایی که می‌شناسند ببینه.\n\nجواب‌ها کاملاً ناشناس‌اند و فقط نتیجه جمعی نمایش داده می‌شود. نسبتت باهاش چیه؟", reply_markup=relation_keyboard())
        return

    await message.answer("<b>فکر می‌کنی بقیه همون‌جوری می‌بیننت که خودت فکر می‌کنی؟</b>\n\nآینه نگاه خودت را با پاسخ ناشناس آدم‌هایی که واقعاً می‌شناسنت مقایسه می‌کند. ساختنش کمتر از دو دقیقه طول می‌کشد.", reply_markup=MAIN_MENU)


@router.message(F.text == "✨ آینه چیه؟")
async def about(message: Message) -> None:
    await message.answer("آینه یک تجربه اجتماعی برای خودشناسیه؛ نه تست روان‌شناسی.\n\nتو چند سؤال درباره خودت جواب می‌دی، لینک را برای دوست‌هات می‌فرستی و بعد می‌بینی نگاه جمعی آن‌ها کجا با تصور خودت فرق دارد. هیچ پاسخ فردی یا اسم پاسخ‌دهنده نمایش داده نمی‌شود.", reply_markup=MAIN_MENU)


@router.message(F.text == "🪞 ساخت آینه من")
async def begin_self_survey(message: Message, state: FSMContext) -> None:
    user = await ensure_user(message)
    mirror = await create_mirror(user.id)
    await state.set_state(SelfSurvey.answering)
    await state.update_data(mirror_id=mirror.id, index=0, scores={})
    await message.answer("عالیه. فقط بر اساس حسی که همین الان نسبت به خودت داری جواب بده؛ جواب درست یا غلطی وجود نداره.")
    await send_question(message, index=0, is_self=True)


@router.callback_query(FriendSurvey.choosing_relation, F.data.startswith("relation:"))
async def choose_relation(callback: CallbackQuery, state: FSMContext) -> None:
    relation = callback.data.split(":", 1)[1]
    if relation not in RELATIONS:
        await callback.answer("گزینه نامعتبره.", show_alert=True)
        return
    await state.set_state(FriendSurvey.answering)
    await state.update_data(relation=relation, index=0, scores={})
    await callback.answer()
    assert callback.message is not None
    await callback.message.edit_text("مرسی. با حسی که واقعاً از این آدم داری جواب بده؛ صاحب آینه هیچ‌وقت نمی‌فهمه تو به هر سؤال چه جوابی دادی.")
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
        await callback.answer("امتیاز نامعتبره.", show_alert=True)
        return
    if value not in range(1, 6):
        await callback.answer("امتیاز نامعتبره.", show_alert=True)
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
        await callback.message.edit_text("<b>آینه‌ات ساخته شد 🪞</b>\n\nحالا لینک را برای حداقل ۳ نفر بفرست. جواب‌ها ناشناس‌اند و فقط نتیجه جمعی را می‌بینی. هرچه آدم‌های بیشتری جواب بدهند، تصویر دقیق‌تر می‌شود.", reply_markup=share_keyboard(invite_link, mirror.owner.first_name))
    else:
        mirror = await get_mirror(mirror_id)
        assert mirror is not None
        stats = await get_stats(mirror_id)
        await callback.message.edit_text("جوابت ثبت شد؛ بدون اسم و بدون نمایش پاسخ‌های تکی. ممنون که صادقانه کمک کردی 🤍\n\nحالا نوبت خودته: از دوست‌هات بپرس واقعاً چطور می‌بیننت.")
        await callback.message.answer("آینه خودت را بساز:", reply_markup=MAIN_MENU)
        with suppress(Exception):
            note = f"یک نفر تازه به آینه‌ات جواب داد 🪞\nتعداد پاسخ‌ها: <b>{stats.respondent_count}</b>"
            if stats.respondent_count == settings.min_responses_for_preview:
                note += "\n\nپیش‌نمایش نتیجه‌ات آماده شد."
            await bot.send_message(mirror.owner.telegram_id, note)


@router.message(F.text == "📊 آینه‌های من")
async def my_mirrors(message: Message) -> None:
    user = await ensure_user(message)
    mirrors = await list_user_mirrors(user.id)
    if not mirrors:
        await message.answer("هنوز آینه‌ای نساختی.", reply_markup=MAIN_MENU)
        return
    await message.answer("آینه‌های اخیرت:")
    for mirror in mirrors:
        stats = await get_stats(mirror.id)
        await message.answer(f"🪞 آینه #{mirror.id}\nپاسخ‌ها: <b>{stats.respondent_count}</b> نفر\nوضعیت گزارش: {'باز شده' if mirror.paid else 'قفل'}", reply_markup=mirror_keyboard(mirror.id, mirror.paid, stats.respondent_count >= settings.min_responses_for_preview))


async def owned_mirror(callback: CallbackQuery, mirror_id: int):
    mirror = await get_mirror(mirror_id)
    if mirror is None or callback.from_user is None or mirror.owner.telegram_id != callback.from_user.id:
        await callback.answer("به این آینه دسترسی نداری.", show_alert=True)
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
    await callback.message.answer(f"این لینک اختصاصی آینه توئه:\n<code>{invite_link}</code>\n\nبرای نتیجه قابل‌اعتماد، برای حداقل ۵ نفر بفرست.", reply_markup=share_keyboard(invite_link, mirror.owner.first_name))


@router.callback_query(F.data.startswith("preview:"))
async def preview(callback: CallbackQuery) -> None:
    mirror_id = int(callback.data.split(":", 1)[1])
    mirror = await owned_mirror(callback, mirror_id)
    if mirror is None:
        return
    stats = await get_stats(mirror_id)
    if stats.respondent_count < settings.min_responses_for_preview:
        await callback.answer(f"برای پیش‌نمایش حداقل {settings.min_responses_for_preview} پاسخ لازمه.", show_alert=True)
        return
    await callback.answer()
    assert callback.message is not None
    await callback.message.answer(preview_text(stats))


@router.callback_query(F.data.startswith("pay:"))
async def pay(callback: CallbackQuery, state: FSMContext) -> None:
    mirror_id = int(callback.data.split(":", 1)[1])
    mirror = await owned_mirror(callback, mirror_id)
    if mirror is None:
        return
    if mirror.paid:
        await callback.answer("گزارشت قبلاً باز شده.")
        return
    if not settings.card_number or not settings.card_holder:
        await callback.answer("اطلاعات پرداخت هنوز توسط مدیر تنظیم نشده.", show_alert=True)
        return
    await state.set_state(PaymentFlow.waiting_receipt)
    await state.update_data(mirror_id=mirror_id)
    await callback.answer()
    assert callback.message is not None
    await callback.message.answer(f"برای بازکردن گزارش کامل، مبلغ <b>{settings.price_label} تومان</b> را کارت‌به‌کارت کن:\n\n<code>{settings.card_display}</code>\nبه نام <b>{settings.card_holder}</b>\n\nبعد تصویر رسید را همین‌جا بفرست. تأیید به‌صورت دستی انجام می‌شود.")


@router.message(PaymentFlow.waiting_receipt, F.photo)
async def receipt_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    await register_receipt(message, state, bot, message.photo[-1].file_id, "photo")


@router.message(PaymentFlow.waiting_receipt, F.document)
async def receipt_document(message: Message, state: FSMContext, bot: Bot) -> None:
    document = message.document
    if document is None or (document.mime_type or "").lower() not in {"image/jpeg", "image/png", "image/webp"}:
        await message.answer("لطفاً تصویر رسید را به‌صورت عکس یا فایل JPG/PNG بفرست.")
        return
    await register_receipt(message, state, bot, document.file_id, "document")


@router.message(PaymentFlow.waiting_receipt)
async def receipt_invalid(message: Message) -> None:
    await message.answer("لطفاً تصویر رسید پرداخت را بفرست.")


async def register_receipt(message: Message, state: FSMContext, bot: Bot, file_id: str, kind: str) -> None:
    assert message.from_user is not None
    data = await state.get_data()
    mirror_id = int(data["mirror_id"])
    mirror = await get_mirror(mirror_id)
    if mirror is None or mirror.owner.telegram_id != message.from_user.id:
        await state.clear()
        await message.answer("آینه پیدا نشد.")
        return
    payment = await create_payment(mirror_id, message.from_user.id, file_id, kind)
    await state.clear()
    await message.answer("رسیدت ثبت شد ✅ بعد از بررسی، نتیجه همین‌جا برات باز می‌شه.", reply_markup=MAIN_MENU)
    caption = f"💳 <b>رسید جدید آینه</b>\nپرداخت #{payment.id}\nآینه #{mirror_id}\nکاربر: <code>{message.from_user.id}</code>"
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
        await callback.answer("دسترسی ادمین نداری.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("درخواست نامعتبره.", show_alert=True)
        return
    action, payment_id_raw = parts[1], parts[2]
    approve = action == "approve"
    if action not in {"approve", "reject"}:
        await callback.answer("درخواست نامعتبره.", show_alert=True)
        return
    payment, mirror = await review_payment(int(payment_id_raw), callback.from_user.id, approve)
    if payment is None or (mirror is None and approve):
        await callback.answer("این رسید قبلاً بررسی شده یا پیدا نشد.", show_alert=True)
        return
    await callback.answer("تأیید شد" if approve else "رد شد")
    assert callback.message is not None
    status = "✅ تأیید شد" if approve else "❌ رد شد"
    with suppress(Exception):
        await callback.message.edit_caption(caption=f"{callback.message.caption or ''}\n\n{status}")
    if approve and mirror:
        await bot.send_message(payment.payer_telegram_id, "پرداختت تأیید شد 🎉 گزارش کامل آینه‌ات باز شد.", reply_markup=mirror_keyboard(mirror.id, True, True))
    else:
        await bot.send_message(payment.payer_telegram_id, "رسید پرداخت تأیید نشد. ممکنه تصویر ناخوانا یا اطلاعات پرداخت اشتباه بوده باشه؛ دوباره از بخش گزارش کامل رسید درست را بفرست.")


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
        await callback.answer("هنوز تعداد پاسخ‌ها برای گزارش کافی نیست.", show_alert=True)
        return
    await callback.answer("دارم آینه‌ات را آماده می‌کنم…")
    assert callback.message is not None
    report_text = mirror.report_text
    if not report_text:
        report_text = await generate_report(settings, mirror.owner.first_name, stats)
        await store_report(mirror.id, report_text)
    await callback.message.answer(report_text)
    try:
        card = make_result_card(mirror.owner.first_name, stats)
        await callback.message.answer_photo(BufferedInputFile(card, filename=f"ayeneh-{mirror.id}.png"), caption="این کارت را می‌تونی برای استوری یا دوست‌هات بفرستی 🪞")
    except Exception:
        logger.exception("Could not create result card for mirror %s", mirror.id)


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    assert message.from_user is not None
    if not is_admin(message.from_user.id):
        return
    values = await admin_stats()
    await message.answer(f"<b>آمار آینه</b>\n\nکاربرها: {values['users']}\nآینه‌ها: {values['mirrors']}\nپاسخ‌دهنده‌ها: {values['responses']}\nپرداخت‌های در انتظار: {values['pending']}\nگزارش‌های بازشده: {values['paid']}")


@router.message(Command("id"))
async def id_command(message: Message) -> None:
    assert message.from_user is not None
    await message.answer(f"شناسه عددی تلگرام شما:\n<code>{message.from_user.id}</code>")


@router.message(F.text.casefold() == "حذف اطلاعات من")
async def delete_data_info(message: Message) -> None:
    await message.answer("حذف کامل داده‌ها نیاز به بررسی مالکیت دارد. شناسه‌ات را با دستور /id بگیر و برای پشتیبانی پروژه ارسال کن. در نسخه بعد، حذف خودکار از داخل ربات اضافه می‌شود.")


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("از دکمه‌های پایین استفاده کن تا آینه‌ات را بسازی یا نتیجه‌هایت را ببینی.", reply_markup=MAIN_MENU)


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
