from __future__ import annotations

import json
import secrets
from collections import defaultdict
from dataclasses import dataclass

from openai import AsyncOpenAI
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.content import TRAITS, TRAIT_BY_KEY
from app.database import SessionLocal
from app.models import Answer, Mirror, Payment, User


@dataclass(frozen=True)
class MirrorStats:
    respondent_count: int
    self_scores: dict[str, float]
    others_scores: dict[str, float]


def _clean_name(value: str | None) -> str:
    return (value or "").strip()[:128]


def _safe_plain_text(value: str) -> str:
    return value.replace("<", "‹").replace(">", "›").strip()


def _percent(score: float | None) -> int:
    return max(0, min(100, round((score or 0) * 20)))


async def upsert_user(
    telegram_id: int,
    first_name: str,
    username: str | None,
) -> User:
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == telegram_id)
        )
        if user is None:
            user = User(
                telegram_id=telegram_id,
                first_name=_clean_name(first_name),
                username=_clean_name(username) or None,
            )
            session.add(user)
        else:
            user.first_name = _clean_name(first_name)
            user.username = _clean_name(username) or None

        await session.commit()
        await session.refresh(user)
        return user


async def create_mirror(user_id: int) -> Mirror:
    """Return the user's current unfinished mirror or create a new one."""
    async with SessionLocal() as session:
        unfinished = await session.scalar(
            select(Mirror)
            .where(
                Mirror.owner_id == user_id,
                Mirror.self_completed.is_(False),
            )
            .order_by(Mirror.created_at.desc())
            .limit(1)
        )
        if unfinished is not None:
            return unfinished

        mirror = Mirror(
            owner_id=user_id,
            token=secrets.token_urlsafe(12),
        )
        session.add(mirror)
        await session.commit()
        await session.refresh(mirror)
        return mirror


async def get_mirror(mirror_id: int) -> Mirror | None:
    async with SessionLocal() as session:
        mirror = await session.scalar(
            select(Mirror)
            .options(selectinload(Mirror.owner))
            .where(Mirror.id == mirror_id)
        )
        if mirror is not None:
            # Reports are regenerated when opened so they stay compatible with
            # the latest wording and include newly received answers.
            mirror.report_text = None
        return mirror


async def get_mirror_by_token(token: str) -> Mirror | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(Mirror)
            .options(selectinload(Mirror.owner))
            .where(Mirror.token == token)
        )


async def list_user_mirrors(owner_id: int) -> list[Mirror]:
    """Only show mirrors whose self survey was actually completed."""
    async with SessionLocal() as session:
        result = await session.scalars(
            select(Mirror)
            .where(
                Mirror.owner_id == owner_id,
                Mirror.self_completed.is_(True),
            )
            .order_by(Mirror.created_at.desc())
            .limit(10)
        )
        return list(result)


async def save_answers(
    mirror_id: int,
    respondent_telegram_id: int,
    scores: dict[str, int],
    *,
    is_self: bool,
    relation: str | None = None,
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(Answer).where(
                Answer.mirror_id == mirror_id,
                Answer.respondent_telegram_id == respondent_telegram_id,
            )
        )
        session.add_all(
            [
                Answer(
                    mirror_id=mirror_id,
                    respondent_telegram_id=respondent_telegram_id,
                    is_self=is_self,
                    relation=relation,
                    trait_key=key,
                    score=max(1, min(5, int(value))),
                )
                for key, value in scores.items()
                if key in TRAIT_BY_KEY
            ]
        )

        if is_self:
            mirror = await session.get(Mirror, mirror_id)
            if mirror:
                mirror.self_completed = True

        await session.commit()


async def has_responded(mirror_id: int, telegram_id: int) -> bool:
    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count(Answer.id)).where(
                Answer.mirror_id == mirror_id,
                Answer.respondent_telegram_id == telegram_id,
                Answer.is_self.is_(False),
            )
        )
        return bool(count)


async def get_stats(mirror_id: int) -> MirrorStats:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    Answer.trait_key,
                    Answer.score,
                    Answer.is_self,
                    Answer.respondent_telegram_id,
                ).where(Answer.mirror_id == mirror_id)
            )
        ).all()

    self_scores: dict[str, list[int]] = defaultdict(list)
    other_scores: dict[str, list[int]] = defaultdict(list)
    respondents: set[int] = set()

    for trait_key, score, is_self, respondent_id in rows:
        if is_self:
            self_scores[trait_key].append(score)
        else:
            other_scores[trait_key].append(score)
            respondents.add(respondent_id)

    def average(values: list[int]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    return MirrorStats(
        respondent_count=len(respondents),
        self_scores={
            key: average(values)
            for key, values in self_scores.items()
        },
        others_scores={
            key: average(values)
            for key, values in other_scores.items()
        },
    )


async def create_payment(
    mirror_id: int,
    payer_telegram_id: int,
    receipt_file_id: str,
    receipt_kind: str,
) -> Payment:
    async with SessionLocal() as session:
        payment = Payment(
            mirror_id=mirror_id,
            payer_telegram_id=payer_telegram_id,
            receipt_file_id=receipt_file_id,
            receipt_kind=receipt_kind,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        return payment


async def review_payment(
    payment_id: int,
    admin_id: int,
    approve: bool,
) -> tuple[Payment | None, Mirror | None]:
    async with SessionLocal() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None or payment.status != "pending":
            return payment, None

        payment.status = "approved" if approve else "rejected"
        payment.reviewed_by = admin_id
        mirror = await session.get(Mirror, payment.mirror_id)
        if mirror and approve:
            mirror.paid = True

        await session.commit()
        return payment, mirror


async def store_report(mirror_id: int, report: str) -> None:
    async with SessionLocal() as session:
        mirror = await session.get(Mirror, mirror_id)
        if mirror:
            mirror.report_text = report
            await session.commit()


def _trait_explanation(key: str, percent: int) -> str:
    level = "high" if percent >= 70 else "medium" if percent >= 45 else "low"

    explanations = {
        "warmth": {
            "high": "بیشتر آدم‌ها کنار تو زودتر احساس راحتی و صمیمیت می‌کنند.",
            "medium": "معمولاً دوستانه‌ای، اما برای صمیمی‌شدن کامل کمی زمان می‌خواهی.",
            "low": "ممکن است در برخورد اول کمی محتاط یا رسمی به نظر برسی.",
        },
        "trust": {
            "high": "بقیه حس می‌کنند می‌توانند روی حرف، همراهی و مسئولیت‌پذیری تو حساب کنند.",
            "medium": "در بیشتر موقعیت‌ها قابل اتکایی، اما احتمالاً این حس برای همه یکسان نیست.",
            "low": "ممکن است بعضی‌ها هنوز برای تکیه‌کردن کامل به تو به زمان یا تجربه بیشتری نیاز داشته باشند.",
        },
        "confidence": {
            "high": "در رفتار و تصمیم‌هایت معمولاً مطمئن و مسلط دیده می‌شوی.",
            "medium": "در بعضی موقعیت‌ها مطمئنی و در بعضی موقعیت‌ها تردیدت دیده می‌شود.",
            "low": "ممکن است با وجود توانایی‌ات، گاهی مردد یا کم‌اطمینان به نظر برسی.",
        },
        "sociability": {
            "high": "معمولاً در جمع حضور فعالی داری و ارتباط‌گرفتن با تو برای بقیه راحت است.",
            "medium": "بسته به جمع و حال‌وهوایت، گاهی اجتماعی و گاهی خلوت‌دوست دیده می‌شوی.",
            "low": "احتمالاً جمع‌های کوچک یا ارتباط‌های عمیق را به شلوغی و آشنایی‌های زیاد ترجیح می‌دهی.",
        },
        "empathy": {
            "high": "آدم‌ها معمولاً حس می‌کنند حرف و احساسشان را جدی می‌گیری و خوب می‌فهمی.",
            "medium": "در بیشتر مواقع همراه و فهمیده‌ای، هرچند همیشه احساساتت را نشان نمی‌دهی.",
            "low": "ممکن است بیشتر راه‌حل بدهی تا اینکه اول احساس طرف مقابل را همراهی کنی.",
        },
        "independence": {
            "high": "در تصمیم‌گیری و پیش‌بردن کارها متکی به خودت دیده می‌شوی.",
            "medium": "هم استقلال داری و هم در بعضی تصمیم‌ها نظر و همراهی دیگران برایت مهم است.",
            "low": "ممکن است برای تصمیم‌های مهم بیشتر به تأیید یا همراهی دیگران نیاز داشته باشی.",
        },
        "calm": {
            "high": "در شرایط سخت معمولاً کنترل خودت را حفظ می‌کنی و به بقیه حس ثبات می‌دهی.",
            "medium": "فشار رویت اثر می‌گذارد، اما اغلب می‌توانی دوباره خودت را جمع‌وجور کنی.",
            "low": "احتمالاً نگرانی یا فشار در رفتارت زودتر دیده می‌شود.",
        },
        "mystery": {
            "high": "آدم‌ها برای شناختن احساسات و لایه‌های شخصی تو به زمان بیشتری نیاز دارند.",
            "medium": "بعضی بخش‌های شخصیتت زود دیده می‌شود و بعضی بخش‌ها را فقط نزدیک‌ها می‌شناسند.",
            "low": "بقیه معمولاً زود می‌فهمند چه حسی داری و چه جور آدمی هستی.",
        },
    }
    return explanations[key][level]


def _recommendation_for_trait(
    key: str,
    own_percent: int,
    others_percent: int,
) -> str:
    if key == "warmth":
        return (
            "در یک گفت‌وگوی مهم، همان صمیمیتی را که بقیه در تو می‌بینند آگاهانه حفظ کن؛ "
            "شروع آرام و دوستانه احتمال شنیده‌شدن حرفت را بیشتر می‌کند."
        )
    if key == "trust":
        return (
            "از یکی از نزدیکانت بپرس دقیقاً کدام رفتار تو بیشترین حس اعتماد را به او می‌دهد؛ "
            "آن رفتار می‌تواند یکی از توانایی‌های اصلی تو باشد."
        )
    if key == "confidence":
        return (
            "دفعه بعد که برای حرف‌زدن یا قبول مسئولیت مردد شدی، قبل از عقب‌کشیدن "
            "یک قدم کوچک بردار؛ نتیجه نشان می‌دهد ممکن است از بیرون آماده‌تر از حس درونی‌ات دیده شوی."
        )
    if key == "sociability":
        return (
            "در جمع بعدی فقط یک بار زودتر وارد گفتگو شو یا خودت یک سؤال بپرس؛ "
            "این کار کمک می‌کند ببینی برداشت بقیه از اجتماعی‌بودنت چقدر درست است."
        )
    if key == "empathy":
        return (
            "وقتی کسی درد دل می‌کند، پیش از پیشنهاد راه‌حل یک جمله بگو که نشان دهد احساسش را فهمیده‌ای؛ "
            "این کار توانایی همدلی تو را روشن‌تر می‌کند."
        )
    if key == "independence":
        return (
            "برای یک تصمیم عقب‌افتاده، معیارهای خودت را روی کاغذ بنویس و زمان مشخصی برای تصمیم نهایی بگذار؛ "
            "این کار استقلالت را به نتیجه عملی تبدیل می‌کند."
        )
    if key == "calm":
        return (
            "در موقعیت پراسترس بعدی، قبل از پاسخ‌دادن چند ثانیه مکث کن و مسئله را به یک قدم بعدی کوچک تبدیل کن؛ "
            "این کار آرامشی را که می‌خواهی نشان بدهی پایدارتر می‌کند."
        )

    relation = (
        "بیشتر از چیزی که فکر می‌کنی"
        if others_percent < own_percent
        else "کمتر از چیزی که فکر می‌کنی"
    )
    return (
        f"به واکنش آدم‌های نزدیکت دقت کن؛ شاید آن‌ها تو را {relation} قابل شناخت می‌بینند. "
        "یک احساس یا نظر کوچک را واضح‌تر بیان کن و واکنششان را ببین."
    )


def fallback_report(owner_name: str, stats: MirrorStats) -> str:
    safe_name = _safe_plain_text(owner_name) or "تو"
    ranked = sorted(
        stats.others_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    if not ranked:
        return (
            f"🪞 گزارش کامل آینه {safe_name}\n\n"
            "هنوز پاسخ کافی برای ساخت گزارش وجود ندارد."
        )

    comparisons: list[tuple[float, str, float, float]] = []
    for trait in TRAITS:
        own = stats.self_scores.get(trait.key)
        others = stats.others_scores.get(trait.key)
        if own is not None and others is not None:
            comparisons.append(
                (others - own, trait.key, own, others)
            )

    positive_gap = max(comparisons, default=(0, ranked[0][0], 0, ranked[0][1]))
    negative_gap = min(comparisons, default=(0, ranked[0][0], 0, ranked[0][1]))
    closest = min(
        comparisons,
        key=lambda item: abs(item[0]),
        default=(0, ranked[0][0], 0, ranked[0][1]),
    )

    top_three = ranked[:3]
    top_titles = "، ".join(
        TRAIT_BY_KEY[key].title
        for key, _ in top_three
    )

    lines = [
        f"🪞 گزارش کامل آینه {safe_name}",
        f"بر اساس {stats.respondent_count} پاسخ ناشناس",
        "",
        "🔎 جمع‌بندی اصلی",
        (
            f"از نگاه آدم‌های اطرافت، سه ویژگی‌ای که بیشتر از همه به چشم آمده "
            f"{top_titles} است. این یعنی برداشت کلی بقیه از تو بیشتر روی همین "
            "ویژگی‌ها شکل گرفته. مهم‌ترین بخش گزارش، فاصله بین نگاه خودت و نگاه "
            "بقیه است؛ چون نشان می‌دهد کجا احتمالاً خودت را کمتر یا بیشتر از چیزی "
            "که دیده می‌شوی ارزیابی کرده‌ای."
        ),
        "",
        "✨ سه ویژگی اصلی تو از نگاه بقیه",
    ]

    medals = ("🥇", "🥈", "🥉")
    for medal, (key, score) in zip(medals, top_three):
        percent = _percent(score)
        lines.extend(
            [
                f"{medal} {TRAIT_BY_KEY[key].title} — {percent}٪",
                _trait_explanation(key, percent),
                "",
            ]
        )

    positive_delta, positive_key, positive_own, positive_others = positive_gap
    if positive_delta > 0:
        lines.extend(
            [
                "🌟 غافلگیری مثبت",
                (
                    f"در «{TRAIT_BY_KEY[positive_key].title}»، خودت {_percent(positive_own)}٪ "
                    f"و بقیه {_percent(positive_others)}٪ امتیاز داده‌اند. "
                    "یعنی این ویژگی بیشتر از چیزی که خودت حس می‌کنی در رفتارت دیده می‌شود. "
                    "این اختلاف می‌تواند نشانه یک توانایی باشد که هنوز به اندازه کافی روی آن حساب نکرده‌ای."
                ),
                "",
            ]
        )

    negative_delta, negative_key, negative_own, negative_others = negative_gap
    if negative_delta < 0:
        lines.extend(
            [
                "⚖️ جایی که برداشت تو و بقیه فرق دارد",
                (
                    f"در «{TRAIT_BY_KEY[negative_key].title}»، امتیاز خودت "
                    f"{_percent(negative_own)}٪ و امتیاز بقیه {_percent(negative_others)}٪ است. "
                    "این الزاماً خوب یا بد نیست؛ فقط نشان می‌دهد چیزی که درون خودت حس می‌کنی "
                    "همیشه به همان شکل به بقیه منتقل نمی‌شود."
                ),
                "",
            ]
        )

    _, closest_key, closest_own, closest_others = closest
    closest_diff = abs(
        _percent(closest_others) - _percent(closest_own)
    )
    lines.extend(
        [
            "🤝 کمترین اختلاف نظر",
            (
                f"در بین هشت ویژگی، کمترین فاصله مربوط به "
                f"«{TRAIT_BY_KEY[closest_key].title}» است: {closest_diff}٪. "
                "یعنی در این بخش، برداشت تو و بقیه از همه بخش‌های دیگر به هم نزدیک‌تر است."
            ),
            "",
            "📊 بررسی هر ۸ ویژگی",
        ]
    )

    for trait in TRAITS:
        own_percent = _percent(stats.self_scores.get(trait.key))
        others_percent = _percent(stats.others_scores.get(trait.key))
        diff = others_percent - own_percent
        if diff >= 10:
            note = "بقیه بیشتر دیده‌اند"
        elif diff <= -10:
            note = "خودت بیشتر حس کرده‌ای"
        else:
            note = "نظرها نزدیک است"

        lines.append(
            f"• {trait.title}: تو {own_percent}٪ | بقیه {others_percent}٪ — {note}"
        )

    recommendation_keys: list[str] = []
    for candidate in (
        positive_key,
        negative_key,
        top_three[0][0],
        closest_key,
        *(trait.key for trait in TRAITS),
    ):
        if candidate not in recommendation_keys:
            recommendation_keys.append(candidate)
        if len(recommendation_keys) == 4:
            break

    lines.extend(["", "💡 پیشنهادهای مخصوص نتیجه تو"])
    for index, key in enumerate(recommendation_keys[:4], start=1):
        lines.append(
            f"{index}️⃣ "
            + _recommendation_for_trait(
                key,
                _percent(stats.self_scores.get(key)),
                _percent(stats.others_scores.get(key)),
            )
        )

    lines.extend(
        [
            "",
            "🧭 چطور از این گزارش استفاده کنی؟",
            "• فقط روی یک اختلاف مهم تمرکز کن، نه همه درصدها.",
            "• از یک دوست قابل‌اعتماد بخواه برای نتیجه‌ای که غافلگیرت کرده یک مثال واقعی بزند.",
            "• بعد از چند هفته دوباره به همان موقعیت‌ها دقت کن و ببین برداشتت تغییر کرده یا نه.",
            "• هرچه تعداد پاسخ‌ها بیشتر و متنوع‌تر باشد، جمع‌بندی قابل اتکاتر می‌شود.",
            "",
            (
                "این گزارش تشخیص روان‌شناسی یا حکم قطعی درباره شخصیت تو نیست؛ "
                "یک جمع‌بندی از پاسخ آدم‌هایی است که تو را می‌شناسند."
            ),
        ]
    )

    return "\n".join(lines)


async def generate_report(
    settings: Settings,
    owner_name: str,
    stats: MirrorStats,
) -> str:
    fallback = fallback_report(owner_name, stats)
    if not settings.openai_api_key:
        return fallback

    payload = {
        "owner_name": _safe_plain_text(owner_name),
        "respondent_count": stats.respondent_count,
        "traits": [
            {
                "key": trait.key,
                "name": trait.title,
                "self_percent": _percent(stats.self_scores.get(trait.key)),
                "others_percent": _percent(stats.others_scores.get(trait.key)),
            }
            for trait in TRAITS
        ],
    }

    prompt = f"""تو نویسنده گزارش فارسی محصول «آینه» هستی.
بر اساس داده‌های زیر یک گزارش مفصل، گرم، دقیق و کاربردی بنویس.

قواعد قطعی:
- فارسی روزمره و طبیعی بنویس؛ جمله‌ها باید شبیه حرف‌زدن یک آدم فارسی‌زبان باشند.
- از عبارت‌های ترجمه‌ای، رسمی یا نامأنوس استفاده نکن.
- این عبارت‌ها ممنوع‌اند: «سخت‌خوان»، «اثر حضور»، «تجربه می‌کنند»،
  «پروفایل شخصیتی»، «تیپ شخصیتی»، «نقطه کور احتمالی».
- کاربر را با «تو» خطاب کن.
- هیچ تشخیص پزشکی، روان‌شناختی یا ادعای قطعی نده.
- درصدها را دقیق نگه دار و هیچ داده‌ای اختراع نکن.
- متن ساده باشد؛ HTML، Markdown و جدول استفاده نکن.
- طول گزارش بین ۲۸۰۰ تا ۳۸۰۰ نویسه باشد.

بخش‌ها دقیقاً:
1) عنوان و تعداد پاسخ‌ها
2) جمع‌بندی اصلی در یک پاراگراف
3) سه ویژگی اصلی؛ برای هرکدام معنی روزمره و کاربردش
4) غافلگیری مثبت: جایی که بقیه امتیاز بیشتری داده‌اند
5) مهم‌ترین اختلاف: جایی که خود کاربر امتیاز بیشتری داده
6) بخشی که نظر کاربر و بقیه نزدیک است
7) مقایسه هر ۸ ویژگی با درصد دقیق
8) چهار پیشنهاد عملی و متفاوت که مستقیماً از داده‌ها آمده باشند
9) راهنمای استفاده درست از نتیجه و محدودیت گزارش

داده‌ها:
{json.dumps(payload, ensure_ascii=False)}
"""

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.responses.create(
            model=settings.openai_model,
            input=prompt,
            store=False,
        )
        text = _safe_plain_text(response.output_text or "")
        if 1800 <= len(text) <= 4000:
            return text
        return fallback
    except Exception:
        return fallback


async def admin_stats() -> dict[str, int]:
    async with SessionLocal() as session:
        users = await session.scalar(
            select(func.count(User.id))
        ) or 0
        mirrors = (
            await session.scalar(
                select(func.count(Mirror.id)).where(
                    Mirror.self_completed.is_(True)
                )
            )
            or 0
        )
        responses = (
            await session.scalar(
                select(
                    func.count(
                        distinct(Answer.respondent_telegram_id)
                    )
                ).where(Answer.is_self.is_(False))
            )
            or 0
        )
        pending = (
            await session.scalar(
                select(func.count(Payment.id)).where(
                    Payment.status == "pending"
                )
            )
            or 0
        )
        paid = (
            await session.scalar(
                select(func.count(Mirror.id)).where(
                    Mirror.paid.is_(True)
                )
            )
            or 0
        )

    return {
        "users": users,
        "mirrors": mirrors,
        "responses": responses,
        "pending": pending,
        "paid": paid,
    }
