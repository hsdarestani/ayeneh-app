from __future__ import annotations

import html

from aiohttp import web

from app.config import Settings


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
        document = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>حریم خصوصی آینه</title><style>body{font-family:Tahoma,Arial,sans-serif;max-width:760px;margin:60px auto;padding:0 24px;line-height:2;color:#292238}h1{font-size:38px}a{color:#654db0}</style></head><body><h1>حریم خصوصی آینه</h1><p>پاسخ افراد به‌صورت ناشناس و فقط در قالب نتیجه جمعی نمایش داده می‌شود. صاحب آینه نام یا پاسخ منفرد افراد را نمی‌بیند.</p><p>شناسه تلگرام فقط برای ورود، جلوگیری از پاسخ تکراری و تحویل نتیجه استفاده می‌شود. رسید پرداخت صرفاً برای بررسی پرداخت نگهداری می‌شود.</p><p>آینه تست یا ابزار تشخیص روان‌شناختی نیست. نتایج صرفاً بازتاب جمعی پاسخ شرکت‌کنندگان است.</p><p>برای حذف داده‌ها، داخل ربات پیام «حذف اطلاعات من» را ارسال کنید.</p><p><a href="/">بازگشت</a></p></body></html>"""
        return web.Response(text=document, content_type="text/html")

    app.router.add_get("/", home)
    app.router.add_get("/health", health)
    app.router.add_get("/privacy", privacy)
    return app
