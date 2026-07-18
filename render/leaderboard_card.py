"""Renders the /bbalb result as a PNG card: the top 10 tracked players for a
single Battle Box Arena stat, plus the requesting user's own rank at the
bottom (only shown if they're linked and ranked outside the top 10)."""
from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw

from render import theme
from render.avatar import get_avatar
from render.shapes import rounded_crop, text_size

CANVAS_W = 720
MARGIN = 28
HEADER_H = 96
ROW_H = 62
ROW_GAP = 10
SEPARATOR_H = 30
FOOTER_GAP = 22
FOOTER_LINE_H = 20
AVATAR_SIZE = 40
RANK_COL_W = 64


def _draw_rank_pill(draw: ImageDraw.ImageDraw, col_left: float, cy: float, text: str, bg, fg) -> None:
    font = theme.label(16)
    pad_x, pad_y = 12, 6
    ink_left, ink_top, ink_right, ink_bottom = draw.textbbox((0, 0), text, font=font)
    w, h = ink_right - ink_left, ink_bottom - ink_top
    pill_w, pill_h = w + 2 * pad_x, h + 2 * pad_y
    cx = col_left + RANK_COL_W / 2
    box = (cx - pill_w / 2, cy - pill_h / 2, cx + pill_w / 2, cy + pill_h / 2)
    draw.rounded_rectangle(box, radius=pill_h / 2, fill=bg)
    draw.text((box[0] + pad_x - ink_left, box[1] + pad_y - ink_top), text, font=font, fill=fg)


def _draw_entry_row(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: float,
    entry: dict,
    value_fmt: Callable[[float], str],
    highlight: bool = False,
) -> None:
    box = (MARGIN, y, CANVAS_W - MARGIN, y + ROW_H)
    bg = theme.ACCENT_SOFT if highlight else theme.CARD_BG
    draw.rounded_rectangle(box, radius=14, fill=bg, outline=theme.BORDER, width=1)

    cy = y + ROW_H / 2
    pill_bg = theme.ACCENT_DARK if highlight else theme.MAIN_SOFT
    pill_fg = theme.BACKGROUND if highlight else theme.MAIN
    _draw_rank_pill(draw, MARGIN + 14, cy, f"#{entry['rank']}", pill_bg, pill_fg)

    avatar = rounded_crop(get_avatar(entry["uuid"], size=AVATAR_SIZE), radius=10)
    avatar_x = MARGIN + 14 + RANK_COL_W + 14
    avatar_y = y + (ROW_H - AVATAR_SIZE) // 2
    img.paste(avatar, (avatar_x, avatar_y), avatar)

    name_x = avatar_x + AVATAR_SIZE + 14
    name_font = theme.label(18)
    name_color = theme.ACCENT_DARK if highlight else theme.TEXT
    display_name = theme.DISPLAY_NAME_OVERRIDES.get(entry["username"].lower(), entry["username"])
    _, n_top, _, n_bottom = draw.textbbox((0, 0), display_name, font=name_font)
    draw.text((name_x, cy - (n_bottom - n_top) / 2 - n_top), display_name, font=name_font, fill=name_color)

    value_text = value_fmt(entry["value"])
    value_font = theme.heading(20)
    v_left, v_top, v_right, v_bottom = draw.textbbox((0, 0), value_text, font=value_font)
    vw = v_right - v_left
    value_color = theme.ACCENT_DARK if highlight else theme.MAIN
    draw.text(
        (CANVAS_W - MARGIN - 18 - vw - v_left, cy - (v_bottom - v_top) / 2 - v_top),
        value_text,
        font=value_font,
        fill=value_color,
    )


def render_leaderboard_card(
    stat_label: str,
    top_entries: list[dict],
    viewer_entry: dict | None,
    tracked_total: int,
    value_fmt: Callable[[float], str],
) -> Image.Image:
    row_count = len(top_entries)
    rows_h = (row_count * ROW_H + max(row_count - 1, 0) * ROW_GAP) if row_count else 28
    viewer_h = (SEPARATOR_H + ROW_H) if viewer_entry else 0
    canvas_h = HEADER_H + 14 + rows_h + viewer_h + FOOTER_GAP + FOOTER_LINE_H + MARGIN

    img = Image.new("RGB", (CANVAS_W, canvas_h), theme.BACKGROUND)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, CANVAS_W, 6), fill=theme.ACCENT)

    draw.text((MARGIN, 26), stat_label, font=theme.heading(26), fill=theme.TEXT)
    draw.text((MARGIN, 60), "Battle Box Arena \u00b7 Top 10", font=theme.body(14), fill=theme.MUTED_TEXT)

    brand_text = "BBA STATS"
    brand_font = theme.heading(16)
    bw, _ = text_size(draw, brand_text, brand_font)
    draw.text((CANVAS_W - MARGIN - bw, 30), brand_text, font=brand_font, fill=theme.MAIN)

    draw.line((MARGIN, HEADER_H, CANVAS_W - MARGIN, HEADER_H), fill=theme.BORDER, width=1)

    y = HEADER_H + 14
    if not top_entries:
        draw.text(
            (MARGIN, y),
            "Not enough tracked players yet for this leaderboard.",
            font=theme.body(15),
            fill=theme.MUTED_TEXT,
        )
        y += 28
    else:
        for i, entry in enumerate(top_entries):
            _draw_entry_row(img, draw, y, entry, value_fmt)
            y += ROW_H
            if i != len(top_entries) - 1:
                y += ROW_GAP

    if viewer_entry:
        y += SEPARATOR_H
        # Three small dots to signal "the list continues" before the viewer's
        # own row -- drawn as shapes rather than a Unicode glyph, since the
        # vertical-ellipsis character isn't in the Lexend font.
        dot_cx = MARGIN + 14 + RANK_COL_W / 2
        dot_r = 2.2
        dot_gap = 7
        dots_cy = y - SEPARATOR_H / 2
        for i in range(-1, 2):
            dcy = dots_cy + i * dot_gap
            draw.ellipse((dot_cx - dot_r, dcy - dot_r, dot_cx + dot_r, dcy + dot_r), fill=theme.MUTED_TEXT)
        _draw_entry_row(img, draw, y, viewer_entry, value_fmt, highlight=True)
        y += ROW_H

    y += FOOTER_GAP
    footer_text = f"Ranks are calculated among {tracked_total:,} player(s) with 100+ games tracked by this bot."
    draw.text((MARGIN, y), footer_text, font=theme.body(13), fill=theme.MUTED_TEXT)

    return img
