from __future__ import annotations

import io
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from app.content import TRAIT_BY_KEY
from app.services import MirrorStats


FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def rtl(text: str) -> str:
    return get_display(arabic_reshaper.reshape(text))


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def make_result_card(owner_name: str, stats: MirrorStats) -> bytes:
    width, height = 1080, 1350
    image = Image.new("RGB", (width, height), (246, 244, 255))
    draw = ImageDraw.Draw(image)

    draw.ellipse((-180, -160, 420, 440), fill=(224, 217, 255))
    draw.ellipse((780, 980, 1280, 1480), fill=(216, 239, 255))
    draw.rounded_rectangle((90, 95, 990, 1255), radius=54, fill=(255, 255, 255))

    title_font = font(66)
    subtitle_font = font(34)
    body_font = font(38)
    percent_font = font(58)

    draw.text((900, 160), rtl("آینه"), font=title_font, fill=(49, 38, 82), anchor="ra")
    draw.text((900, 245), rtl(f"{owner_name} از نگاه آدم‌های اطرافش"), font=subtitle_font, fill=(96, 87, 122), anchor="ra")

    ranked = sorted(stats.others_scores.items(), key=lambda item: item[1], reverse=True)[:3]
    y = 390
    for key, score in ranked:
        percent = round(score * 20)
        draw.rounded_rectangle((150, y, 930, y + 190), radius=34, fill=(247, 246, 252))
        draw.text((850, y + 48), rtl(TRAIT_BY_KEY[key].title), font=body_font, fill=(57, 49, 76), anchor="ra")
        draw.text((225, y + 45), rtl(f"{percent}٪"), font=percent_font, fill=(83, 67, 140), anchor="la")
        bar_left, bar_right = 225, 850
        draw.rounded_rectangle((bar_left, y + 132, bar_right, y + 150), radius=9, fill=(222, 218, 233))
        fill_right = bar_left + int((bar_right - bar_left) * percent / 100)
        draw.rounded_rectangle((bar_left, y + 132, fill_right, y + 150), radius=9, fill=(126, 106, 196))
        y += 225

    draw.text((540, 1130), rtl(f"بر اساس {stats.respondent_count} پاسخ ناشناس"), font=subtitle_font, fill=(104, 95, 126), anchor="ma")
    draw.text((540, 1190), "ayeneh.smarbiz.sbs", font=font(28), fill=(126, 116, 148), anchor="ma")

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
