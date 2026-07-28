"""Small Pillow drawing helpers shared across card renderers.

Shape primitives that would otherwise look jagged (rounded rects, ellipses,
stars, crop masks, polygons, thick lines) are drawn via supersampling: paint
at AA_SCALE× resolution, then Lanczos-downsample so edges anti-alias cleanly.
TrueType text is already AA'd by FreeType, so plain `draw.text` is left alone.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from PIL import Image, ImageDraw

# 3× is a good quality/cost tradeoff for Discord-sized cards.
AA_SCALE = 3


def _rgba(color) -> tuple[int, int, int, int] | None:
    if color is None:
        return None
    if len(color) == 4:
        return color  # type: ignore[return-value]
    return (color[0], color[1], color[2], 255)


def _paste_rgba(base: Image.Image, overlay: Image.Image, xy: tuple[int, int]) -> None:
    """Alpha-composites `overlay` onto `base` at `xy`, preserving base mode."""
    x, y = xy
    ow, oh = overlay.size
    bx0, by0 = max(x, 0), max(y, 0)
    bx1, by1 = min(x + ow, base.width), min(y + oh, base.height)
    if bx0 >= bx1 or by0 >= by1:
        return
    ox0, oy0 = bx0 - x, by0 - y
    ox1, oy1 = ox0 + (bx1 - bx0), oy0 + (by1 - by0)
    piece = overlay if (ox0, oy0, ox1, oy1) == (0, 0, ow, oh) else overlay.crop((ox0, oy0, ox1, oy1))
    if base.mode == "RGBA":
        base.alpha_composite(piece, (bx0, by0))
        return
    region = base.crop((bx0, by0, bx1, by1)).convert("RGBA")
    region = Image.alpha_composite(region, piece)
    base.paste(region.convert(base.mode), (bx0, by0))


def rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1):
    """Legacy thin wrapper — prefer aa_rounded_rectangle(image, ...) for smooth edges."""
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def aa_rounded_rectangle(
    image: Image.Image,
    box,
    radius: float,
    fill=None,
    outline=None,
    width: int = 1,
    scale: int = AA_SCALE,
) -> None:
    """Anti-aliased rounded rectangle composited onto `image`."""
    x0, y0, x1, y1 = (
        int(math.floor(box[0])),
        int(math.floor(box[1])),
        int(math.ceil(box[2])),
        int(math.ceil(box[3])),
    )
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return
    pad = max(int(width), 1) + 1
    layer = Image.new("RGBA", ((w + 2 * pad) * scale, (h + 2 * pad) * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rect = (pad * scale, pad * scale, (pad + w) * scale - 1, (pad + h) * scale - 1)
    d.rounded_rectangle(
        rect,
        radius=max(radius, 0) * scale,
        fill=_rgba(fill),
        outline=_rgba(outline),
        width=max(int(width), 0) * scale,
    )
    layer = layer.resize((w + 2 * pad, h + 2 * pad), Image.Resampling.LANCZOS)
    _paste_rgba(image, layer, (x0 - pad, y0 - pad))


def aa_ellipse(
    image: Image.Image,
    box,
    fill=None,
    outline=None,
    width: int = 1,
    scale: int = AA_SCALE,
) -> None:
    """Anti-aliased ellipse/circle composited onto `image`."""
    x0, y0, x1, y1 = (
        int(math.floor(box[0])),
        int(math.floor(box[1])),
        int(math.ceil(box[2])),
        int(math.ceil(box[3])),
    )
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return
    pad = max(int(width), 1) + 1
    layer = Image.new("RGBA", ((w + 2 * pad) * scale, (h + 2 * pad) * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rect = (pad * scale, pad * scale, (pad + w) * scale - 1, (pad + h) * scale - 1)
    d.ellipse(rect, fill=_rgba(fill), outline=_rgba(outline), width=max(int(width), 0) * scale)
    layer = layer.resize((w + 2 * pad, h + 2 * pad), Image.Resampling.LANCZOS)
    _paste_rgba(image, layer, (x0 - pad, y0 - pad))


def aa_line(
    image: Image.Image,
    xy: Sequence[float],
    fill,
    width: int = 1,
    scale: int = AA_SCALE,
) -> None:
    """Anti-aliased straight or polyline. `xy` is a flat sequence or list of points."""
    if xy and isinstance(xy[0], (list, tuple)):
        points = [(float(p[0]), float(p[1])) for p in xy]  # type: ignore[index]
    else:
        flat = list(xy)
        points = [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat) - 1, 2)]
    if len(points) < 2:
        return

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    pad = max(int(width), 1) + 2
    x0, y0 = int(math.floor(min_x)) - pad, int(math.floor(min_y)) - pad
    x1, y1 = int(math.ceil(max_x)) + pad, int(math.ceil(max_y)) + pad
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return

    layer = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    scaled = [((px - x0) * scale, (py - y0) * scale) for px, py in points]
    d.line(scaled, fill=_rgba(fill), width=max(int(width), 1) * scale, joint="curve")
    layer = layer.resize((w, h), Image.Resampling.LANCZOS)
    _paste_rgba(image, layer, (x0, y0))


def aa_polygon(
    image: Image.Image,
    points: Sequence[tuple[float, float]],
    fill=None,
    outline=None,
    width: int = 1,
    scale: int = AA_SCALE,
) -> None:
    """Anti-aliased filled/outlined polygon composited onto `image`."""
    if len(points) < 3:
        return
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    pad = max(int(width), 1) + 2
    x0, y0 = int(math.floor(min(xs))) - pad, int(math.floor(min(ys))) - pad
    x1, y1 = int(math.ceil(max(xs))) + pad, int(math.ceil(max(ys))) + pad
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return

    layer = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    scaled = [((px - x0) * scale, (py - y0) * scale) for px, py in points]
    d.polygon(scaled, fill=_rgba(fill), outline=_rgba(outline) if outline and width <= 1 else None)
    if outline and width > 1:
        d.line(scaled + [scaled[0]], fill=_rgba(outline), width=width * scale, joint="curve")
    layer = layer.resize((w, h), Image.Resampling.LANCZOS)
    _paste_rgba(image, layer, (x0, y0))


def circular_crop(image: Image.Image) -> Image.Image:
    """Circular crop with an anti-aliased mask edge."""
    size = image.size
    scale = AA_SCALE
    mask_hi = Image.new("L", (size[0] * scale, size[1] * scale), 0)
    ImageDraw.Draw(mask_hi).ellipse((0, 0, size[0] * scale - 1, size[1] * scale - 1), fill=255)
    mask = mask_hi.resize(size, Image.Resampling.LANCZOS)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    src = image.convert("RGBA") if image.mode != "RGBA" else image
    out.paste(src, (0, 0), mask)
    return out


def rounded_crop(image: Image.Image, radius: int) -> Image.Image:
    """Rounded-rect crop with an anti-aliased mask edge."""
    size = image.size
    scale = AA_SCALE
    mask_hi = Image.new("L", (size[0] * scale, size[1] * scale), 0)
    ImageDraw.Draw(mask_hi).rounded_rectangle(
        (0, 0, size[0] * scale - 1, size[1] * scale - 1),
        radius=radius * scale,
        fill=255,
    )
    mask = mask_hi.resize(size, Image.Resampling.LANCZOS)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    src = image.convert("RGBA") if image.mode != "RGBA" else image
    out.paste(src, (0, 0), mask)
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


def draw_star(image_or_draw, cx: float, cy: float, r: float, fill) -> None:
    """Draws a small filled 5-point star with anti-aliased edges.

    Accepts either an Image (preferred) or a legacy ImageDraw for call-site
    compatibility — if given a Draw, falls back to the jagged polygon path.
    """
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = r if i % 2 == 0 else r * 0.42
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    if isinstance(image_or_draw, Image.Image):
        aa_polygon(image_or_draw, points, fill=fill)
        return

    image_or_draw.polygon(points, fill=fill)


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
    return row.resize((width, max(height, 1)), Image.Resampling.LANCZOS)


def aa_rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    """Anti-aliased L-mode rounded-rect mask for clipping pasted content."""
    w, h = size
    scale = AA_SCALE
    hi = Image.new("L", (w * scale, h * scale), 0)
    ImageDraw.Draw(hi).rounded_rectangle(
        (0, 0, w * scale - 1, h * scale - 1),
        radius=radius * scale,
        fill=255,
    )
    return hi.resize((w, h), Image.Resampling.LANCZOS)


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


def downsample(image: Image.Image, scale: int = 2) -> Image.Image:
    """Lanczos-downsample a supersampled canvas back to logical size."""
    if scale <= 1:
        return image
    w, h = image.size
    return image.resize((max(w // scale, 1), max(h // scale, 1)), Image.Resampling.LANCZOS)
