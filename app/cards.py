from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from app.content import TRAIT_BY_KEY
from app.services import MirrorStats


ARABIC_REGULAR_FONTS = (
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

ARABIC_BOLD_FONTS = (
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

GENERAL_REGULAR_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
)

GENERAL_BOLD_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
)

PERSIAN_DIGIT_TABLE = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def rtl(text: str) -> str:
    """Shape and reorder Persian text for Pillow."""
    return get_display(arabic_reshaper.reshape(text))


def fa_number(value: int | str) -> str:
    return str(value).translate(PERSIAN_DIGIT_TABLE)


def _load_font(candidates: Iterable[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def arabic_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_font(ARABIC_BOLD_FONTS if bold else ARABIC_REGULAR_FONTS, size)


def general_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_font(GENERAL_BOLD_FONTS if bold else GENERAL_REGULAR_FONTS, size)


def _safe_name(name: str, max_length: int = 22) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        return "تو"
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1]}…"


def make_result_card(owner_name: str, stats: MirrorStats) -> bytes:
    width, height = 1080, 1350
    image = Image.new("RGB", (width, height), (241, 239, 252))
    draw = ImageDraw.Draw(image)

    # Soft background shapes.
    draw.ellipse((-260, -210, 390, 440), fill=(220, 211, 255))
    draw.ellipse((770, 1010, 1320, 1560), fill=(205, 235, 255))
    draw.rounded_rectangle(
        (62, 62, 1018, 1288),
        radius=58,
        fill=(255, 255, 255),
        outline=(229, 225, 244),
        width=3,
    )

    title_font = arabic_font(76, bold=True)
    subtitle_font = general_font(38)
    trait_font = arabic_font(42, bold=True)
    percent_font = general_font(46, bold=True)
    small_font = arabic_font(31)
    footer_font = general_font(27)

    safe_owner = _safe_name(owner_name)

    # Header.
    draw.text(
        (912, 135),
        rtl("آینه"),
        font=title_font,
        fill=(48, 36, 82),
        anchor="ra",
    )
    draw.text(
        (912, 224),
        rtl(f"{safe_owner} از نگاه آدم‌های اطرافش"),
        font=subtitle_font,
        fill=(103, 94, 126),
        anchor="ra",
    )

    count_label = rtl(f"بر اساس {fa_number(stats.respondent_count)} پاسخ ناشناس")
    draw.rounded_rectangle(
        (120, 122, 430, 202),
        radius=28,
        fill=(244, 241, 252),
    )
    draw.text(
        (275, 162),
        count_label,
        font=small_font,
        fill=(96, 79, 137),
        anchor="mm",
    )

    draw.line((120, 285, 960, 285), fill=(234, 231, 242), width=3)

    ranked = sorted(
        stats.others_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:3]

    y = 330
    for key, score in ranked:
        percent = max(0, min(100, round(score * 20)))
        trait_title = TRAIT_BY_KEY[key].title

        draw.rounded_rectangle(
            (120, y, 960, y + 202),
            radius=38,
            fill=(248, 247, 252),
        )

        # Trait title.
        draw.text(
            (870, y + 47),
            rtl(trait_title),
            font=trait_font,
            fill=(55, 47, 72),
            anchor="ra",
        )

        # Percentage badge. Draw digits directly so their order never flips.
        draw.rounded_rectangle(
            (145, y + 32, 315, y + 112),
            radius=28,
            fill=(111, 88, 183),
        )
        draw.text(
            (230, y + 72),
            f"{fa_number(percent)}٪",
            font=percent_font,
            fill=(255, 255, 255),
            anchor="mm",
        )

        # Progress bar.
        bar_left, bar_right = 145, 870
        bar_top, bar_bottom = y + 145, y + 171
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_right, bar_bottom),
            radius=13,
            fill=(224, 220, 235),
        )
        fill_right = bar_left + int((bar_right - bar_left) * percent / 100)
        if fill_right > bar_left:
            draw.rounded_rectangle(
                (bar_left, bar_top, fill_right, bar_bottom),
                radius=13,
                fill=(126, 101, 202),
            )

        y += 232

    # Footer.
    draw.rounded_rectangle(
        (120, 1050, 960, 1180),
        radius=34,
        fill=(245, 242, 252),
    )
    draw.text(
        (540, 1090),
        rtl("سه ویژگی پررنگ تو از نگاه دیگران"),
        font=arabic_font(35, bold=True),
        fill=(66, 54, 91),
        anchor="mm",
    )
    draw.text(
        (540, 1142),
        rtl("این نتیجه فقط از میانگین پاسخ‌ها ساخته شده"),
        font=small_font,
        fill=(112, 102, 133),
        anchor="mm",
    )

    # Use a Latin-capable font for the domain; this fixes the square glyphs.
    draw.text(
        (540, 1234),
        "ayeneh.smarbiz.sbs",
        font=footer_font,
        fill=(126, 116, 148),
        anchor="mm",
    )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
