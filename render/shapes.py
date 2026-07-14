"""Small Pillow drawing helpers shared across card renderers."""
from __future__ import annotations

import math

from PIL import Image, ImageDraw


def rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def circular_crop(image: Image.Image) -> Image.Image:
    size = image.size
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size[0], size[1]), fill=255)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return out


def rounded_crop(image: Image.Image, radius: int) -> Image.Image:
    size = image.size
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return out


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Greedily wraps `text` into lines that each fit within max_width."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and text_size(draw, candidate, font)[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def draw_gradient_text(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    font,
    color_start: tuple[int, int, int],
    color_end: tuple[int, int, int],
) -> None:
    """Draws `text` filled with a left-to-right linear gradient, blended onto `image`."""
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((-left, -top), text, font=font, fill=255)

    gradient = Image.new("RGB", (w, 1))
    for i in range(w):
        t = i / max(w - 1, 1)
        gradient.putpixel(
            (i, 0),
            (
                round(color_start[0] + (color_end[0] - color_start[0]) * t),
                round(color_start[1] + (color_end[1] - color_start[1]) * t),
                round(color_start[2] + (color_end[2] - color_start[2]) * t),
            ),
        )
    gradient = gradient.resize((w, h))

    image.paste(gradient, (xy[0] + left, xy[1] + top), mask)


def draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    """Draws a small filled 5-point star centered at (cx, cy) with outer radius r."""
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = r if i % 2 == 0 else r * 0.42
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=fill)


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, font_fn, start_size: int, min_size: int):
    """Shrinks `font_fn(size)` down from start_size to min_size until `text` fits max_width.

    Returns (font, text) where `text` may be ellipsis-truncated if it still doesn't
    fit at min_size.
    """
    size = start_size
    font = font_fn(size)
    while size > min_size and text_size(draw, text, font)[0] > max_width:
        size -= 1
        font = font_fn(size)

    if text_size(draw, text, font)[0] <= max_width:
        return font, text

    truncated = text
    while len(truncated) > 1 and text_size(draw, truncated + "\u2026", font)[0] > max_width:
        truncated = truncated[:-1]
    return font, truncated + "\u2026"
