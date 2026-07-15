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


def build_gradient_bar(
    width: int,
    height: int,
    segments: list[tuple[float, tuple[int, int, int]]],
    blend: int = 18,
) -> Image.Image:
    """Builds a horizontal bar image where adjacent segment colors blend smoothly
    into each other at their boundaries, instead of a hard color cut.

    `segments` is a list of (proportion, rgb_color); proportions don't need to
    sum to 1, they're normalized internally.
    """
    segments = [s for s in segments if s[0] > 0] or [(1.0, (0, 0, 0))]
    width = max(width, 1)
    total = sum(p for p, _ in segments)

    boundaries = [0.0]
    acc = 0.0
    for p, _ in segments:
        acc += p
        boundaries.append(acc / total * width)
    colors = [c for _, c in segments]

    # Clamp the blend radius so it can't spill past adjacent boundaries on thin segments.
    if len(segments) > 1:
        min_gap = min(boundaries[i + 1] - boundaries[i] for i in range(len(segments)))
        blend = max(2, min(blend, int(min_gap)))

    row = Image.new("RGB", (width, 1))
    for x in range(width):
        idx = len(segments) - 1
        for i in range(len(segments)):
            if x < boundaries[i + 1]:
                idx = i
                break
        color = colors[idx]
        if idx > 0:
            boundary = boundaries[idx]
            half = blend / 2
            if boundary - half <= x <= boundary + half:
                t = (x - (boundary - half)) / blend
                c0, c1 = colors[idx - 1], colors[idx]
                color = tuple(round(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
        row.putpixel((x, 0), color)
    return row.resize((width, max(height, 1)))


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
