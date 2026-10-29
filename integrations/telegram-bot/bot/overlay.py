"""Draw a tile's number (and a play icon for videos) onto its thumbnail.

Telegram shows a collage's per-photo captions nowhere (checked live), so the number that
the keep buttons use has to be part of the image itself.
"""

import io
import logging

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Telegram crops a collage tile to about 2:3 at its tallest (seen live: 282x610 screenshots
# lose their top and bottom), so crop first or the badge lands in the part that is cut off.
_MIN_ASPECT = 2 / 3


def label(data: bytes, number: int, is_video: bool) -> bytes:
    """`data` with a badge in the top-left corner; unchanged if it can't be decoded."""
    try:
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        width, height = image.size
        if width / height < _MIN_ASPECT:
            keep = round(width / _MIN_ASPECT)
            top_edge = (height - keep) // 2
            image = image.crop((0, top_edge, width, top_edge + keep))
            height = keep
        unit = max(18, min(width, height) // 7)
        font = ImageFont.load_default(size=unit)
        text = str(number)
        left, top, right, bottom = font.getbbox(text)
        pad = unit // 3
        icon = unit if is_video else 0
        gap = pad if is_video else 0
        box_w = pad + icon + gap + (right - left) + pad
        box_h = pad + (bottom - top) + pad
        origin = max(4, unit // 4)
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.rounded_rectangle(
            (origin, origin, origin + box_w, origin + box_h),
            radius=pad,
            fill=(0, 0, 0, 170),
        )
        if is_video:
            x, y = origin + pad, origin + pad
            draw.polygon(
                [(x, y), (x, y + (bottom - top)), (x + icon, y + (bottom - top) // 2)],
                fill=(255, 255, 255, 255),
            )
        draw.text(
            (origin + pad + icon + gap - left, origin + pad - top),
            text,
            font=font,
            fill=(255, 255, 255, 255),
        )
        out = io.BytesIO()
        Image.alpha_composite(image, layer).convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:
        logger.warning("Could not label a thumbnail; sending it as is")
        return data
