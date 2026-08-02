from __future__ import annotations

from app.content import TRAIT_BY_KEY
from app.services import MirrorStats


def demo_stats() -> MirrorStats:
    return MirrorStats(
        respondent_count=7,
        self_scores={
            "warmth": 3.2,
            "trust": 4.0,
            "confidence": 2.4,
            "sociability": 2.8,
            "empathy": 4.1,
            "independence": 3.8,
            "calm": 2.9,
            "mystery": 4.0,
        },
        others_scores={
            "warmth": 4.4,
            "trust": 4.6,
            "confidence": 3.8,
            "sociability": 3.6,
            "empathy": 4.3,
            "independence": 4.0,
            "calm": 3.1,
            "mystery": 3.2,
        },
    )


def demo_report_text() -> str:
    return (
        "🎁 <b>نمونه گزارش کامل آینه</b>\n"
        "<i>این نمونه با اطلاعات فرضی ساخته شده تا دقیقاً ببینی بعد از پرداخت چه چیزی می‌گیری.</i>\n\n"
        "🪞 <b>تصویر کلی سارا</b>\n"
        "سارا خودش را کمی کم‌حرف و محتاط می‌بیند؛ اما آدم‌های اطرافش حضور او را گرم‌تر، مطمئن‌تر و اجتماعی‌تر از چیزی تجربه کرده‌اند که خودش تصور می‌کند. بیشترین توافق درباره قابل‌اعتماد بودن و همدلی اوست.\n\n"
        "✨ <b>سه ویژگی پررنگ از نگاه دیگران</b>\n"
        "🥇 قابل‌اعتماد بودن — ۹۲٪\n"
        "🥈 گرمی و صمیمیت — ۸۸٪\n"
        "🥉 همدلی — ۸۶٪\n\n"
        "👀 <b>بزرگ‌ترین غافلگیری</b>\n"
        "سارا اعتمادبه‌نفس خودش را ۴۸٪ ارزیابی کرده؛ درحالی‌که دیگران آن را ۷۶٪ دیده‌اند. یعنی احتمالاً اثر حضور و اطمینانی که به بقیه منتقل می‌کند، بیشتر از چیزی است که خودش حس می‌کند.\n\n"
        "🤝 <b>جایی که نگاه‌ها شبیه هم بود</b>\n"
        "در «استقلال» فاصله نگاه سارا و اطرافیانش فقط ۴٪ بوده؛ پس تصویری که از تصمیم‌گیری مستقل خودش دارد، با تجربه بقیه هم‌خوان است.\n\n"
        "💡 <b>یک برداشت کاربردی</b>\n"
        "وقتی قرار است در جمعی تازه حرف بزند یا مسئولیتی را قبول کند، بهتر است به تصویری که دیگران از اعتمادبه‌نفسش دارند بیشتر تکیه کند؛ احتمالاً از بیرون آماده‌تر و قوی‌تر از چیزی دیده می‌شود که درون خودش احساس می‌کند.\n\n"
        "📊 <b>مقایسه هر ۸ ویژگی</b>\n"
        "• صمیمیت: خودت ۶۴٪ | دیگران ۸۸٪\n"
        "• اعتماد: خودت ۸۰٪ | دیگران ۹۲٪\n"
        "• اعتمادبه‌نفس: خودت ۴۸٪ | دیگران ۷۶٪\n"
        "• اجتماعی بودن: خودت ۵۶٪ | دیگران ۷۲٪\n"
        "• همدلی: خودت ۸۲٪ | دیگران ۸۶٪\n"
        "• استقلال: خودت ۷۶٪ | دیگران ۸۰٪\n"
        "• آرامش در فشار: خودت ۵۸٪ | دیگران ۶۲٪\n"
        "• مرموز بودن: خودت ۸۰٪ | دیگران ۶۴٪\n\n"
        "🖼 همراه گزارش واقعی، یک کارت تصویری شخصی هم می‌گیری که می‌تونی برای استوری یا دوست‌هات بفرستی.\n\n"
        "<i>گزارش واقعی تو با پاسخ‌های دوستان خودت ساخته می‌شه؛ بنابراین متن و نتیجه برای هر نفر متفاوته.</i>"
    )


def preview_text(stats: MirrorStats) -> str:
    if not stats.others_scores:
        return "⏳ هنوز کسی به آینه‌ات جواب نداده. لینک را برای چند نفر بفرست تا اولین نتیجه ساخته شود."

    ranked = sorted(stats.others_scores.items(), key=lambda item: item[1], reverse=True)
    top_key, top_score = ranked[0]
    top_percent = round(top_score * 20)

    gaps: list[tuple[float, str, float, float]] = []
    for key, others_score in stats.others_scores.items():
        own_score = stats.self_scores.get(key)
        if own_score is not None:
            gaps.append((abs(others_score - own_score), key, own_score, others_score))

    surprise = ""
    if gaps:
        _, gap_key, own_score, others_score = max(gaps)
        own_percent = round(own_score * 20)
        others_percent = round(others_score * 20)
        if others_score > own_score:
            sentence = "دیگران این ویژگی را در تو پررنگ‌تر از چیزی می‌بینند که خودت فکر می‌کنی."
        elif others_score < own_score:
            sentence = "خودت این ویژگی را پررنگ‌تر از چیزی می‌بینی که دیگران تجربه می‌کنند."
        else:
            sentence = "نگاه تو و دیگران در این ویژگی تقریباً یکی است."
        surprise = (
            "\n\n🤯 <b>جالب‌ترین تفاوت تا اینجا</b>\n"
            f"{TRAIT_BY_KEY[gap_key].title}: خودت <b>{own_percent}٪</b> | دیگران <b>{others_percent}٪</b>\n"
            f"{sentence}"
        )

    return (
        "👀 <b>پیش‌نمایش رایگان آینه‌ات</b>\n"
        f"این نتیجه فعلاً بر اساس <b>{stats.respondent_count} پاسخ ناشناس</b> ساخته شده.\n\n"
        "✨ <b>چیزی که بیشتر از همه در تو دیده شده</b>\n"
        f"{TRAIT_BY_KEY[top_key].title} — <b>{top_percent}٪</b>"
        f"{surprise}\n\n"
        "🔒 <b>داخل گزارش کامل چه می‌بینی؟</b>\n"
        "• تصویر کلی و شخصی‌سازی‌شده از نگاه اطرافیان\n"
        "• سه ویژگی پررنگ تو با توضیح\n"
        "• بزرگ‌ترین نقطه کور یا غافلگیری\n"
        "• مقایسه نگاه خودت و بقیه در هر ۸ ویژگی\n"
        "• یک پیشنهاد کاربردی مخصوص نتیجه خودت\n"
        "• کارت تصویری آماده برای استوری\n\n"
        "این فقط یک تکه از آینه‌اته؛ گزارش کامل با داده‌های واقعی خودت نوشته می‌شه 🪞"
    )
