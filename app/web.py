from __future__ import annotations

import html
import logging
import secrets
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout, web
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.database import SessionLocal
from app.models import GatewayPayment, Mirror, utcnow
from app.payments import ZibalError, request_zibal_payment, valid_payment_signature, verify_zibal_payment, zibal_payment_url

logger = logging.getLogger("ayeneh.web")


def _page(
    *,
    title: str,
    message: str,
    icon: str,
    action_url: str | None = None,
    action_label: str | None = None,
    reference: str | None = None,
) -> web.Response:
    safe_title = html.escape(title)
    safe_message = html.escape(message).replace("\n", "<br>")
    action = ""
    if action_url and action_label:
        action = f'<a class="cta" href="{html.escape(action_url, quote=True)}">{html.escape(action_label)}</a>'
    reference_html = f'<small>شناسه پیگیری: {html.escape(reference)}</small>' if reference else ""
    document = f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title} — آینه</title>
<style>
:root{{--ink:#251d39;--muted:#726985;--violet:#7357c7;--line:#e8e1f5}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:Tahoma,Arial,sans-serif;background:radial-gradient(circle at 20% 10%,#e5ddff 0,transparent 32%),radial-gradient(circle at 90% 85%,#dff4ff 0,transparent 30%),#faf9ff;color:var(--ink);min-height:100vh}}
main{{width:min(680px,calc(100% - 28px));margin:auto;min-height:100vh;display:grid;place-items:center;padding:36px 0}}
.card{{width:100%;background:rgba(255,255,255,.86);border:1px solid rgba(255,255,255,.95);border-radius:34px;padding:clamp(28px,7vw,58px);box-shadow:0 30px 100px rgba(67,49,112,.14);backdrop-filter:blur(18px);text-align:center}}
.icon{{font-size:58px;line-height:1}}
h1{{font-size:clamp(30px,8vw,48px);margin:22px 0 12px}}
p{{font-size:18px;line-height:2;color:var(--muted);margin:0 auto 28px;max-width:520px}}
.cta{{display:inline-flex;align-items:center;justify-content:center;min-height:58px;padding:0 30px;border-radius:18px;background:var(--ink);color:#fff;text-decoration:none;font-weight:700;font-size:17px;box-shadow:0 16px 35px rgba(37,29,57,.22)}}
small{{display:block;margin-top:22px;color:#91899d;direction:ltr}}
</style>
</head>
<body><main><section class="card"><div class="icon">{html.escape(icon)}</div><h1>{safe_title}</h1><p>{safe_message}</p>{action}{reference_html}</section></main></body>
</html>"""
    return web.Response(text=document, content_type="text/html", charset="utf-8")


async def _telegram_notify_paid(settings: Settings, *, telegram_id: int, mirror_id: int) -> None:
    if not settings.bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": telegram_id,
        "parse_mode": "HTML",
        "text": (
            "🎉 <b>پرداختت با موفقیت تأیید شد!</b>\n\n"
            "گزارش کامل آینه‌ات باز شده. روی دکمه زیر بزن و نتیجه‌ات را ببین 👇"
        ),
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "📖 دیدن گزارش کامل من", "callback_data": f"report:{mirror_id}"}
            ]]
        },
    }
    try:
        timeout = ClientTimeout(total=15, connect=6)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
    except (ClientError, TimeoutError):
        logger.exception("Could not notify Telegram user %s after payment", telegram_id)


def make_web_app(settings: Settings, bot_username: str) -> web.Application:
    app = web.Application()
    safe_bot = html.escape(bot_username)
    bot_url = f"https://t.me/{safe_bot}"

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "ayeneh"})

    async def home(_: web.Request) -> web.Response:
        document = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>آینه — خودت را از چشم دیگران ببین</title><meta name="description" content="یک تجربه ناشناس و جمعی برای دیدن تفاوت نگاه خودت و آدم‌های اطرافت."><style>:root{{--ink:#251d39;--muted:#726985;--violet:#7357c7;--soft:#f5f2ff;--line:#e8e1f5}}*{{box-sizing:border-box}}body{{margin:0;font-family:Tahoma,Arial,sans-serif;background:radial-gradient(circle at 20% 10%,#e5ddff 0,transparent 32%),radial-gradient(circle at 90% 85%,#dff4ff 0,transparent 30%),#faf9ff;color:var(--ink);min-height:100vh}}main{{width:min(920px,calc(100% - 32px));margin:auto;min-height:100vh;display:grid;place-items:center;padding:48px 0}}.card{{width:100%;background:rgba(255,255,255,.78);border:1px solid rgba(255,255,255,.9);border-radius:40px;padding:clamp(28px,7vw,72px);box-shadow:0 30px 100px rgba(67,49,112,.12);backdrop-filter:blur(18px);text-align:center}}.logo{{width:92px;height:92px;border-radius:30px;margin:auto;display:grid;place-items:center;background:linear-gradient(145deg,#8066d4,#5d44ae);color:white;font-size:44px;box-shadow:0 18px 45px rgba(93,68,174,.28)}}h1{{font-size:clamp(42px,9vw,78px);margin:24px 0 8px;letter-spacing:-3px}}.lead{{font-size:clamp(19px,4vw,29px);line-height:1.85;color:var(--muted);max-width:670px;margin:0 auto 28px}}.cta{{display:inline-flex;align-items:center;justify-content:center;min-height:62px;padding:0 34px;border-radius:20px;background:var(--ink);color:white;text-decoration:none;font-weight:700;font-size:18px;box-shadow:0 16px 35px rgba(37,29,57,.24);transition:.2s}}.cta:hover{{transform:translateY(-2px)}}.features{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:36px}}.feature{{padding:18px 12px;border:1px solid var(--line);border-radius:18px;background:#fff;color:var(--muted)}}small{{display:block;margin-top:25px;color:#91899d}}footer{{margin-top:24px;font-size:13px}}footer a{{color:var(--muted)}}@media(max-width:620px){{.card{{border-radius:28px;padding:32px 20px}}.features{{grid-template-columns:1fr}}}}</style></head><body><main><section class="card"><div class="logo">🪞</div><h1>آینه</h1><p class="lead">فکر می‌کنی بقیه همون‌جوری می‌بیننت که خودت فکر می‌کنی؟ آینه نگاه تو را با پاسخ ناشناس آدم‌هایی که واقعاً می‌شناسنت مقایسه می‌کند.</p><a class="cta" href="{bot_url}">ساخت آینه من در تلگرام</a><div class="features"><div class="feature">کاملاً ناشناس</div><div class="feature">فقط چند سؤال کوتاه</div><div class="feature">گزارش شخصی و قابل اشتراک</div></div><small>آینه ابزار تشخیص روان‌شناختی نیست.</small><footer><a href="/privacy">حریم خصوصی</a></footer></section></main></body></html>"""
        return web.Response(text=document, content_type="text/html")

    async def privacy(_: web.Request) -> web.Response:
        document = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>حریم خصوصی آینه</title><style>body{font-family:Tahoma,Arial,sans-serif;max-width:760px;margin:60px auto;padding:0 24px;line-height:2;color:#292238}h1{font-size:38px}a{color:#654db0}</style></head><body><h1>حریم خصوصی آینه</h1><p>پاسخ افراد به‌صورت ناشناس و فقط در قالب نتیجه جمعی نمایش داده می‌شود. صاحب آینه نام یا پاسخ منفرد افراد را نمی‌بیند.</p><p>شناسه تلگرام فقط برای ورود، جلوگیری از پاسخ تکراری و تحویل نتیجه استفاده می‌شود. برای پرداخت، فقط شناسه‌های فنی تراکنش و وضعیت تأیید زیبال نگهداری می‌شود؛ اطلاعات کارت بانکی کامل در آینه ذخیره نمی‌شود.</p><p>آینه تست یا ابزار تشخیص روان‌شناختی نیست. نتایج صرفاً بازتاب جمعی پاسخ شرکت‌کنندگان است.</p><p>برای حذف داده‌ها، داخل ربات پیام «حذف اطلاعات من» را ارسال کنید.</p><p><a href="/">بازگشت</a></p></body></html>"""
        return web.Response(text=document, content_type="text/html")

    async def payment_start(request: web.Request) -> web.StreamResponse:
        try:
            mirror_id = int(request.match_info["mirror_id"])
        except (KeyError, ValueError):
            return _page(title="لینک نامعتبر", message="لینک پرداخت درست نیست. دوباره از داخل ربات وارد شو.", icon="⚠️", action_url=bot_url, action_label="بازگشت به ربات")

        if not valid_payment_signature(settings, mirror_id, request.query.get("sig", "")):
            return _page(title="لینک نامعتبر", message="اعتبار لینک پرداخت قابل تأیید نیست. دوباره از داخل ربات روی دکمه پرداخت بزن.", icon="🔒", action_url=bot_url, action_label="بازگشت به ربات")
        if not settings.zibal_merchant:
            return _page(title="پرداخت موقتاً در دسترس نیست", message="درگاه پرداخت هنوز روی سرور تنظیم نشده است.", icon="🛠️", action_url=bot_url, action_label="بازگشت به ربات")

        async with SessionLocal() as session:
            mirror = await session.scalar(
                select(Mirror)
                .options(selectinload(Mirror.owner))
                .where(Mirror.id == mirror_id)
            )
            if mirror is None or not mirror.self_completed:
                return _page(title="آینه پیدا نشد", message="این آینه وجود ندارد یا هنوز کامل نشده است.", icon="⚠️", action_url=bot_url, action_label="بازگشت به ربات")
            if mirror.paid:
                return _page(title="گزارش قبلاً باز شده", message="پرداخت این آینه قبلاً تأیید شده و گزارش کامل داخل ربات در دسترس است.", icon="✅", action_url=bot_url, action_label="دیدن گزارش در ربات")

            order_id = f"ayeneh-{mirror_id}-{secrets.token_hex(8)}"
            payment = GatewayPayment(
                mirror_id=mirror_id,
                payer_telegram_id=mirror.owner.telegram_id,
                amount_rial=settings.price_rial,
                order_id=order_id,
            )
            session.add(payment)
            await session.commit()
            await session.refresh(payment)
            payment_id = payment.id

        try:
            track_id = await request_zibal_payment(
                settings,
                amount_rial=settings.price_rial,
                order_id=order_id,
                description=f"گزارش کامل آینه شماره {mirror_id}",
            )
        except ZibalError as exc:
            async with SessionLocal() as session:
                payment = await session.get(GatewayPayment, payment_id)
                if payment:
                    payment.status = "request_failed"
                    payment.result_code = exc.result
                    await session.commit()
            logger.warning("Zibal request failed for mirror %s: %s", mirror_id, exc)
            return _page(title="اتصال به درگاه انجام نشد", message="درگاه پرداخت پاسخ نداد. چند لحظه بعد دوباره از داخل ربات امتحان کن.", icon="🔄", action_url=bot_url, action_label="بازگشت به ربات")

        async with SessionLocal() as session:
            payment = await session.get(GatewayPayment, payment_id)
            if payment:
                payment.track_id = track_id
                payment.status = "requested"
                payment.result_code = 100
                await session.commit()

        raise web.HTTPFound(zibal_payment_url(track_id))

    async def payment_callback(request: web.Request) -> web.Response:
        values: dict[str, str] = {key: value for key, value in request.query.items()}
        if request.can_read_body:
            try:
                form = await request.post()
                values.update({key: str(value) for key, value in form.items()})
            except (ValueError, ClientError):
                pass

        raw_track_id = values.get("trackId") or values.get("trackid") or values.get("TrackId")
        order_id = values.get("orderId") or values.get("orderid") or values.get("OrderId")
        try:
            track_id = int(raw_track_id or "")
        except ValueError:
            track_id = 0

        async with SessionLocal() as session:
            payment = None
            if track_id:
                payment = await session.scalar(select(GatewayPayment).where(GatewayPayment.track_id == track_id))
            if payment is None and order_id:
                payment = await session.scalar(select(GatewayPayment).where(GatewayPayment.order_id == order_id))
            if payment is None:
                return _page(title="تراکنش پیدا نشد", message="شناسه این پرداخت در آینه پیدا نشد. از داخل ربات دوباره پرداخت را شروع کن.", icon="⚠️", action_url=bot_url, action_label="بازگشت به ربات")

            mirror = await session.get(Mirror, payment.mirror_id)
            if mirror is None:
                return _page(title="آینه پیدا نشد", message="پرداخت ثبت شده، اما آینه مربوط به آن پیدا نشد.", icon="⚠️", action_url=bot_url, action_label="بازگشت به ربات")
            if payment.status == "verified" or mirror.paid:
                return _page(title="پرداخت موفق", message="پرداخت قبلاً تأیید شده و گزارش کامل داخل ربات باز است.", icon="✅", action_url=bot_url, action_label="دیدن گزارش در ربات", reference=str(payment.ref_number or payment.track_id or payment.id))
            payment_id = payment.id
            expected_amount = payment.amount_rial
            payer_telegram_id = payment.payer_telegram_id
            mirror_id = payment.mirror_id
            stored_track_id = payment.track_id

        verify_track_id = track_id or stored_track_id
        if not verify_track_id:
            return _page(title="تأیید پرداخت ممکن نشد", message="شناسه پیگیری زیبال دریافت نشده است. دوباره از داخل ربات پرداخت را شروع کن.", icon="⚠️", action_url=bot_url, action_label="بازگشت به ربات")

        try:
            verification = await verify_zibal_payment(settings, verify_track_id)
        except ZibalError:
            logger.exception("Zibal verification failed for track %s", verify_track_id)
            return _page(title="وضعیت پرداخت نامشخص است", message="ارتباط با زیبال برای تأیید نهایی برقرار نشد. همین صفحه را دوباره باز کن؛ مبلغ دوباره برداشت نمی‌شود.", icon="🔄", action_url=str(request.url), action_label="بررسی دوباره", reference=str(verify_track_id))

        result = verification.result
        payload = verification.payload
        paid_amount_raw = payload.get("amount")
        try:
            paid_amount = int(paid_amount_raw) if paid_amount_raw is not None else None
        except (TypeError, ValueError):
            paid_amount = None

        successful = result in {100, 201}
        amount_matches = paid_amount is None or paid_amount == expected_amount
        if not successful or not amount_matches:
            async with SessionLocal() as session:
                payment = await session.get(GatewayPayment, payment_id)
                if payment:
                    payment.status = "amount_mismatch" if successful and not amount_matches else "failed"
                    payment.result_code = result
                    await session.commit()
            message = "مبلغ تأییدشده با مبلغ سفارش یکسان نیست." if successful and not amount_matches else "پرداخت کامل نشده یا توسط بانک لغو شده است."
            return _page(title="پرداخت تأیید نشد", message=f"{message}\nمی‌توانی دوباره از داخل ربات اقدام کنی.", icon="❌", action_url=bot_url, action_label="بازگشت به ربات", reference=str(verify_track_id))

        ref_number = str(payload.get("refNumber") or payload.get("refId") or payload.get("referenceNumber") or verify_track_id)
        card_number = payload.get("cardNumber")
        async with SessionLocal() as session:
            payment = await session.get(GatewayPayment, payment_id)
            mirror = await session.get(Mirror, mirror_id)
            if payment is None or mirror is None:
                return _page(title="ثبت نهایی انجام نشد", message="پرداخت در زیبال تأیید شد، اما ثبت داخلی کامل نشد. صفحه را دوباره باز کن.", icon="🔄", action_url=str(request.url), action_label="تلاش دوباره", reference=ref_number)
            if payment.status != "verified":
                payment.status = "verified"
                payment.result_code = result
                payment.ref_number = ref_number
                payment.card_number = str(card_number)[:32] if card_number else None
                payment.verified_at = utcnow()
            mirror.paid = True
            await session.commit()

        await _telegram_notify_paid(settings, telegram_id=payer_telegram_id, mirror_id=mirror_id)
        return _page(title="پرداخت موفق", message="پرداختت تأیید شد و گزارش کامل آینه داخل ربات باز شد.", icon="✅", action_url=bot_url, action_label="دیدن گزارش در ربات", reference=ref_number)

    app.router.add_get("/", home)
    app.router.add_get("/health", health)
    app.router.add_get("/privacy", privacy)
    app.router.add_get("/payment/start/{mirror_id}", payment_start)
    app.router.add_get("/payment/callback", payment_callback)
    app.router.add_post("/payment/callback", payment_callback)
    return app
