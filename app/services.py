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


async def upsert_user(telegram_id: int, first_name: str, username: str | None) -> User:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(telegram_id=telegram_id, first_name=_clean_name(first_name), username=_clean_name(username) or None)
            session.add(user)
        else:
            user.first_name = _clean_name(first_name)
            user.username = _clean_name(username) or None
        await session.commit()
        await session.refresh(user)
        return user


async def create_mirror(user_id: int) -> Mirror:
    async with SessionLocal() as session:
        mirror = Mirror(owner_id=user_id, token=secrets.token_urlsafe(12))
        session.add(mirror)
        await session.commit()
        await session.refresh(mirror)
        return mirror


async def get_mirror(mirror_id: int) -> Mirror | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Mirror).options(selectinload(Mirror.owner)).where(Mirror.id == mirror_id))


async def get_mirror_by_token(token: str) -> Mirror | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Mirror).options(selectinload(Mirror.owner)).where(Mirror.token == token))


async def list_user_mirrors(owner_id: int) -> list[Mirror]:
    async with SessionLocal() as session:
        result = await session.scalars(select(Mirror).where(Mirror.owner_id == owner_id).order_by(Mirror.created_at.desc()).limit(10))
        return list(result)


async def save_answers(mirror_id: int, respondent_telegram_id: int, scores: dict[str, int], *, is_self: bool, relation: str | None = None) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Answer).where(Answer.mirror_id == mirror_id, Answer.respondent_telegram_id == respondent_telegram_id))
        session.add_all([Answer(mirror_id=mirror_id, respondent_telegram_id=respondent_telegram_id, is_self=is_self, relation=relation, trait_key=key, score=max(1, min(5, int(value)))) for key, value in scores.items() if key in TRAIT_BY_KEY])
        if is_self:
            mirror = await session.get(Mirror, mirror_id)
            if mirror:
                mirror.self_completed = True
        await session.commit()


async def has_responded(mirror_id: int, telegram_id: int) -> bool:
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count(Answer.id)).where(Answer.mirror_id == mirror_id, Answer.respondent_telegram_id == telegram_id, Answer.is_self.is_(False)))
        return bool(count)


async def get_stats(mirror_id: int) -> MirrorStats:
    async with SessionLocal() as session:
        rows = (await session.execute(select(Answer.trait_key, Answer.score, Answer.is_self, Answer.respondent_telegram_id).where(Answer.mirror_id == mirror_id))).all()
    self_scores: dict[str, list[int]] = defaultdict(list)
    other_scores: dict[str, list[int]] = defaultdict(list)
    respondents: set[int] = set()
    for trait_key, score, is_self, respondent_id in rows:
        if is_self:
            self_scores[trait_key].append(score)
        else:
            other_scores[trait_key].append(score)
            respondents.add(respondent_id)
    average = lambda values: round(sum(values) / len(values), 2) if values else 0.0
    return MirrorStats(len(respondents), {key: average(values) for key, values in self_scores.items()}, {key: average(values) for key, values in other_scores.items()})


async def create_payment(mirror_id: int, payer_telegram_id: int, receipt_file_id: str, receipt_kind: str) -> Payment:
    async with SessionLocal() as session:
        payment = Payment(mirror_id=mirror_id, payer_telegram_id=payer_telegram_id, receipt_file_id=receipt_file_id, receipt_kind=receipt_kind)
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        return payment


async def review_payment(payment_id: int, admin_id: int, approve: bool) -> tuple[Payment | None, Mirror | None]:
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


def preview_text(stats: MirrorStats) -> str:
    if not stats.others_scores:
        return "هنوز پاسخی ثبت نشده."
    ranked = sorted(stats.others_scores.items(), key=lambda item: item[1], reverse=True)
    top_key, top_score = ranked[0]
    gaps = []
    for key, others_score in stats.others_scores.items():
        if key in stats.self_scores:
            gaps.append((abs(others_score - stats.self_scores[key]), key, others_score - stats.self_scores[key]))
    gap_line = ""
    if gaps:
        _, gap_key, delta = max(gaps)
        direction = "بیشتر" if delta > 0 else "کمتر"
        gap_line = f"\n\nبزرگ‌ترین تفاوت: دیگران «{TRAIT_BY_KEY[gap_key].title}» تو را {direction} از چیزی می‌بینند که خودت فکر می‌کنی."
    return f"👀 <b>یک تکه از آینه‌ات</b>\n\nپررنگ‌ترین ویژگی تو از نگاه دیگران: <b>{TRAIT_BY_KEY[top_key].title}</b> ({round(top_score * 20)}٪){gap_line}\n\nگزارش کامل، تفاوت نگاه خودت و بقیه را برای همه ویژگی‌ها نشان می‌دهد."


def fallback_report(owner_name: str, stats: MirrorStats) -> str:
    lines = [f"🪞 <b>گزارش کامل آینه {owner_name}</b>", ""]
    ranked = sorted(stats.others_scores.items(), key=lambda item: item[1], reverse=True)
    if ranked:
        lines.append("<b>ویژگی‌هایی که بیشتر از همه دیده شده‌اند</b>")
        for key, score in ranked[:3]:
            lines.append(f"• {TRAIT_BY_KEY[key].title}: {round(score * 20)}٪")
        lines.append("")
    gaps = []
    for trait in TRAITS:
        own = stats.self_scores.get(trait.key)
        others = stats.others_scores.get(trait.key)
        if own and others:
            gaps.append((abs(others - own), trait, own, others))
    if gaps:
        _, trait, own, others = max(gaps)
        insight = "اطرافیانت این ویژگی را در تو پررنگ‌تر از چیزی می‌بینند که خودت حس می‌کنی." if others > own else "خودت این ویژگی را پررنگ‌تر از چیزی می‌بینی که دیگران تجربه می‌کنند."
        lines.extend(["<b>نقطه کور احتمالی</b>", f"در «{trait.title}»، نگاه تو {round(own * 20)}٪ و نگاه دیگران {round(others * 20)}٪ است. {insight}", ""])
    lines.append("<b>جدول نگاه تو و دیگران</b>")
    for trait in TRAITS:
        own = round(stats.self_scores.get(trait.key, 0) * 20)
        others = round(stats.others_scores.get(trait.key, 0) * 20)
        lines.append(f"• {trait.title}: تو {own}٪ | دیگران {others}٪")
    lines.extend(["", "این نتیجه تشخیص روان‌شناختی نیست؛ یک تصویر جمعی از تجربه آدم‌های اطراف توست."])
    return "\n".join(lines)


async def generate_report(settings: Settings, owner_name: str, stats: MirrorStats) -> str:
    if not settings.openai_api_key:
        return fallback_report(owner_name, stats)
    payload = {"owner_name": owner_name, "respondent_count": stats.respondent_count, "traits": [{"name": trait.title, "self_percent": round(stats.self_scores.get(trait.key, 0) * 20), "others_percent": round(stats.others_scores.get(trait.key, 0) * 20)} for trait in TRAITS]}
    prompt = f"""تو نویسنده گزارش محصول فارسی «آینه» هستی. از داده‌های زیر یک گزارش کوتاه، دقیق، گرم و بدون قضاوت بنویس.
- گزارش باید فارسی باشد و حداکثر 500 کلمه.
- از ادعاهای تشخیصی، پزشکی و قطعی خودداری کن.
- با HTML ساده تلگرام بنویس و فقط از تگ‌های <b> و <i> استفاده کن.
- بخش‌ها: تصویر کلی، سه ویژگی پررنگ، بزرگ‌ترین تفاوت نگاه خود و دیگران، یک پیشنهاد عملی، یادآوری اینکه نتیجه تشخیص روان‌شناختی نیست.
- درصدها را دقیق نگه دار؛ چیزی اختراع نکن.
داده‌ها:
{json.dumps(payload, ensure_ascii=False)}"""
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.responses.create(model=settings.openai_model, input=prompt, store=False)
        text = (response.output_text or "").strip()
        return text or fallback_report(owner_name, stats)
    except Exception:
        return fallback_report(owner_name, stats)


async def admin_stats() -> dict[str, int]:
    async with SessionLocal() as session:
        users = await session.scalar(select(func.count(User.id))) or 0
        mirrors = await session.scalar(select(func.count(Mirror.id))) or 0
        responses = await session.scalar(select(func.count(distinct(Answer.respondent_telegram_id))).where(Answer.is_self.is_(False))) or 0
        pending = await session.scalar(select(func.count(Payment.id)).where(Payment.status == "pending")) or 0
        paid = await session.scalar(select(func.count(Mirror.id)).where(Mirror.paid.is_(True))) or 0
    return {"users": users, "mirrors": mirrors, "responses": responses, "pending": pending, "paid": paid}
