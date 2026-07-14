"""Renders the /bbastats result as a PNG card.

Layout is organized into labeled sections (Overview / Combat / Placements &
Objectives / Damage Breakdown) rather than one flat grid, so it reads more
like a dashboard than a straight box-grid.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from render import theme
from render.avatar import get_avatar
from render.shapes import draw_gradient_text, draw_star, fit_font, rounded_crop, text_size
from stats.derive import METRICS, compute_all

# Individual stat thresholds behind MCC Island's "Expert" LFG tier. Being accepted
# requires meeting 3 of 6 categories (several of which have an and/or pair of
# stats) plus player approval -- we just mark each stat that individually clears
# its own bar with a tiny gold star, rather than compute the aggregate tier.
EXPERT_THRESHOLDS: dict[str, float] = {
    "wlr": 1.5,
    "round_win_pct": 60.0,
    "kills_per_game": 5.0,
    "kills_per_round": 0.8,
    "assists_per_game": 3.6,
    "assists_per_round": 0.6,
    "coins_per_round": 45.0,
    "top1_pct": 25.0,
    "top3_pct": 60.0,
}


def _meets_expert(key: str, value: float) -> bool:
    threshold = EXPERT_THRESHOLDS.get(key)
    return threshold is not None and value >= threshold

CANVAS_W = 1000
MARGIN = 32
HEADER_H = 148
GRID_GAP = 18
COLS = 4
COL_W = (CANVAS_W - 2 * MARGIN - (COLS - 1) * GRID_GAP) // COLS
CONTENT_W = CANVAS_W - 2 * MARGIN

OVERVIEW_H = 104
ROW_H = 148
SECTION_LABEL_H = 34
DAMAGE_BAR_H = 116
FOOTER_H = 80

# (main_metric_key, [sub_metric_keys])
OVERVIEW_ROW: list[tuple[str, list[str]]] = [
    ("games_played", []),
    ("games_won", []),
    ("wlr", []),
    ("kd", []),
]

COMBAT_ROW: list[tuple[str, list[str]]] = [
    ("kills_per_game", ["kills_per_round", "total_kills"]),
    ("deaths_per_game", ["deaths_per_round", "total_deaths"]),
    ("assists_per_game", ["assists_per_round", "total_assists"]),
    ("aces_per_game", ["aces_per_round", "total_aces"]),
]

PLACEMENTS_ROW: list[tuple[str, list[str]]] = [
    ("round_win_pct", ["total_rounds_played"]),
    ("coins_per_game", ["coins_per_round", "total_coins"]),
    ("top1_pct", ["total_top1"]),
    ("top3_pct", ["total_top3"]),
]


@dataclass
class _RenderContext:
    values: dict[str, float]
    percentiles: dict[str, dict]


def _draw_rank_badge(draw: ImageDraw.ImageDraw, x_right: int, y: int, text: str) -> None:
    font = theme.label(15)
    w, h = text_size(draw, text, font)
    pad_x, pad_y = 10, 5
    box = (x_right - w - 2 * pad_x, y, x_right, y + h + 2 * pad_y)
    draw.rounded_rectangle(box, radius=(h + 2 * pad_y) // 2, fill=theme.MAIN_SOFT)
    draw.text((box[0] + pad_x, box[1] + pad_y - 1), text, font=font, fill=theme.MAIN)


def _draw_section_label(draw: ImageDraw.ImageDraw, y: int, text: str) -> None:
    tick_h = 16
    tick_y = y + (SECTION_LABEL_H - tick_h) // 2
    draw.rounded_rectangle((MARGIN, tick_y, MARGIN + 4, tick_y + tick_h), radius=2, fill=theme.MAIN)
    draw.text((MARGIN + 14, y + 2), text.upper(), font=theme.label(15), fill=theme.MUTED_TEXT)


def _draw_stat_box(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    spec: tuple[str, list[str]],
    ctx: _RenderContext,
    value_font_size: int = 30,
) -> None:
    main_key, sub_keys = spec
    box = (x, y, x + w, y + h)
    draw.rounded_rectangle(box, radius=16, fill=theme.CARD_BG, outline=theme.BORDER, width=1)

    pad = 16
    inner_x = x + pad
    cur_y = y + pad

    label_text = METRICS[main_key].label.upper()
    rank = ctx.percentiles.get(main_key, {}).get("rank")

    badge_reserved = 0
    if rank:
        badge_font = theme.label(15)
        badge_reserved = text_size(draw, f"#{rank}", badge_font)[0] + 2 * 10 + 10  # pill padding + gap

    available_w = w - 2 * pad - badge_reserved
    label_font, label_text = fit_font(draw, label_text, available_w, lambda s: theme.label(s), 13, 10)
    draw.text((inner_x, cur_y), label_text, font=label_font, fill=theme.MUTED_TEXT)

    if rank:
        _draw_rank_badge(draw, x + w - pad, cur_y - 4, f"#{rank}")

    cur_y += text_size(draw, "A", theme.label(13))[1] + 10

    value_font = theme.heading(value_font_size)
    value_text = METRICS[main_key].fmt(ctx.values[main_key])
    draw.text((inner_x, cur_y), value_text, font=value_font, fill=theme.TEXT)
    value_w, value_h = text_size(draw, value_text, value_font)

    if _meets_expert(main_key, ctx.values[main_key]):
        # Center the star on the glyphs' actual ink extents, not the font's full
        # line-height box (digits have no descenders, so those differ).
        ink_left, ink_top, ink_right, ink_bottom = draw.textbbox((inner_x, cur_y), value_text, font=value_font)
        star_r = value_font_size * 0.24
        star_cx = ink_right + 12 + star_r
        star_cy = (ink_top + ink_bottom) / 2
        draw_star(draw, star_cx, star_cy, star_r, theme.GOLD)

    cur_y += value_h + 14

    sub_font = theme.body(13)
    sub_val_font = theme.label(13)
    for sub_key in sub_keys:
        sub_label = METRICS[sub_key].label
        sub_value_text = METRICS[sub_key].fmt(ctx.values[sub_key])
        sub_rank = ctx.percentiles.get(sub_key, {}).get("rank")
        rank_text = f"#{sub_rank}" if sub_rank else None
        sub_qualifies = _meets_expert(sub_key, ctx.values[sub_key])
        star_r = 4.5
        star_reserved = (2 * star_r + 6) if sub_qualifies else 0

        right_edge = x + w - pad
        value_w, sub_val_h = text_size(draw, sub_value_text, sub_val_font)
        reserved = value_w + star_reserved
        if rank_text:
            rank_w, _ = text_size(draw, rank_text, sub_font)
            reserved += rank_w + 8

        label_available_w = w - 2 * pad - reserved - 10
        fitted_font, fitted_label = fit_font(draw, sub_label, label_available_w, lambda s: theme.body(s), 13, 10)
        draw.text((inner_x, cur_y), fitted_label, font=fitted_font, fill=theme.MUTED_TEXT)

        if rank_text:
            rank_w, _ = text_size(draw, rank_text, sub_font)
            draw.text((right_edge - rank_w, cur_y), rank_text, font=sub_font, fill=theme.MAIN)
            right_edge -= rank_w + 8

        if sub_qualifies:
            # Center on the actual ink extents of the value text at its final drawn
            # position, so the star lines up with the digits rather than the font box.
            ink_top, ink_bottom = draw.textbbox((0, cur_y), sub_value_text, font=sub_val_font)[1::2]
            draw_star(draw, right_edge - star_r, (ink_top + ink_bottom) / 2, star_r, theme.GOLD)
            right_edge -= star_reserved

        draw.text((right_edge - value_w, cur_y), sub_value_text, font=sub_val_font, fill=theme.TEXT)
        cur_y += text_size(draw, sub_label, sub_font)[1] + 8


def _draw_row(
    draw: ImageDraw.ImageDraw, y: int, h: int, specs: list[tuple[str, list[str]]], ctx: _RenderContext, value_font_size: int = 30
) -> None:
    for col_idx, spec in enumerate(specs):
        x = MARGIN + col_idx * (COL_W + GRID_GAP)
        _draw_stat_box(draw, x, y, COL_W, h, spec, ctx, value_font_size=value_font_size)


def _draw_damage_breakdown(draw: ImageDraw.ImageDraw, y: int, ctx: _RenderContext) -> None:
    box = (MARGIN, y, MARGIN + CONTENT_W, y + DAMAGE_BAR_H)
    draw.rounded_rectangle(box, radius=16, fill=theme.CARD_BG, outline=theme.BORDER, width=1)

    pad = 20
    melee_pct = max(min(ctx.values["melee_pct"], 100.0), 0.0)
    ranged_pct = max(min(ctx.values["ranged_pct"], 100.0), 0.0)
    other_pct = max(0.0, 100.0 - melee_pct - ranged_pct)

    bar_x = MARGIN + pad
    bar_w = CONTENT_W - 2 * pad
    bar_y = y + pad + 8
    bar_h = 22

    segments = [
        (melee_pct, theme.MAIN),
        (ranged_pct, theme.ACCENT),
        (other_pct, theme.BORDER),
    ]
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=bar_h // 2, fill=theme.BORDER)
    cursor_x = bar_x
    total = sum(s[0] for s in segments) or 1
    for pct, color in segments:
        seg_w = round(bar_w * pct / total)
        if seg_w <= 0:
            continue
        draw.rounded_rectangle(
            (cursor_x, bar_y, min(cursor_x + seg_w, bar_x + bar_w), bar_y + bar_h), radius=bar_h // 2, fill=color
        )
        cursor_x += seg_w

    legend_y = bar_y + bar_h + 18
    swatch = 12
    legend_font = theme.body(14)
    value_font = theme.label(14)

    def _legend_entry(lx: int, color, label_text: str, value_text: str, rank_key: str | None) -> int:
        draw.rounded_rectangle((lx, legend_y + 3, lx + swatch, legend_y + 3 + swatch), radius=3, fill=color)
        lx += swatch + 8
        draw.text((lx, legend_y), label_text, font=legend_font, fill=theme.MUTED_TEXT)
        lx += text_size(draw, label_text, legend_font)[0] + 8
        draw.text((lx, legend_y), value_text, font=value_font, fill=theme.TEXT)
        lx += text_size(draw, value_text, value_font)[0]
        if rank_key:
            rank = ctx.percentiles.get(rank_key, {}).get("rank")
            if rank:
                lx += 8
                rank_text = f"#{rank}"
                draw.text((lx, legend_y), rank_text, font=legend_font, fill=theme.MAIN)
                lx += text_size(draw, rank_text, legend_font)[0]
        return lx + 28

    lx = bar_x
    lx = _legend_entry(lx, theme.MAIN, "Melee", METRICS["melee_pct"].fmt(melee_pct), "melee_pct")
    lx = _legend_entry(lx, theme.ACCENT, "Ranged", METRICS["ranged_pct"].fmt(ranged_pct), "ranged_pct")
    _legend_entry(lx, theme.BORDER, "Other", f"{other_pct:.1f}%", None)


def render_stats_card(username: str, uuid: str, raw: dict, percentiles: dict, tracked_total: int) -> Image.Image:
    ctx = _RenderContext(values=compute_all(raw), percentiles=percentiles)

    canvas_h = (
        HEADER_H
        + 22
        + OVERVIEW_H
        + GRID_GAP
        + SECTION_LABEL_H
        + ROW_H
        + GRID_GAP
        + SECTION_LABEL_H
        + ROW_H
        + GRID_GAP
        + SECTION_LABEL_H
        + DAMAGE_BAR_H
        + GRID_GAP
        + FOOTER_H
        + MARGIN
    )

    img = Image.new("RGB", (CANVAS_W, canvas_h), theme.BACKGROUND)
    draw = ImageDraw.Draw(img)

    # Single sparing accent highlight: a thin top border strip.
    draw.rectangle((0, 0, CANVAS_W, 6), fill=theme.ACCENT)

    avatar_size = 88
    avatar = rounded_crop(get_avatar(uuid, size=avatar_size), radius=18)
    avatar_x, avatar_y = MARGIN, 30
    img.paste(avatar, (avatar_x, avatar_y), avatar)
    draw.rounded_rectangle(
        (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), radius=18, outline=theme.BORDER, width=2
    )

    name_x = avatar_x + avatar_size + 20
    name_font = theme.heading(30)
    gradient = theme.NAME_GRADIENTS.get(username.lower())
    if gradient:
        draw_gradient_text(img, (name_x, avatar_y + 4), username, name_font, *gradient)
    else:
        draw.text((name_x, avatar_y + 4), username, font=name_font, fill=theme.TEXT)
    draw.text(
        (name_x, avatar_y + 44),
        "Battle Box Arena \u00b7 Lifetime Statistics",
        font=theme.body(16),
        fill=theme.MUTED_TEXT,
    )

    brand_text = "BBA STATS"
    brand_font = theme.heading(18)
    bw, _ = text_size(draw, brand_text, brand_font)
    draw.text((CANVAS_W - MARGIN - bw, 34), brand_text, font=brand_font, fill=theme.MAIN)

    draw.line((MARGIN, HEADER_H, CANVAS_W - MARGIN, HEADER_H), fill=theme.BORDER, width=1)

    y = HEADER_H + 22
    _draw_row(draw, y, OVERVIEW_H, OVERVIEW_ROW, ctx, value_font_size=26)
    y += OVERVIEW_H + GRID_GAP

    _draw_section_label(draw, y, "Combat")
    y += SECTION_LABEL_H
    _draw_row(draw, y, ROW_H, COMBAT_ROW, ctx)
    y += ROW_H + GRID_GAP

    _draw_section_label(draw, y, "Placements & Objectives")
    y += SECTION_LABEL_H
    _draw_row(draw, y, ROW_H, PLACEMENTS_ROW, ctx)
    y += ROW_H + GRID_GAP

    _draw_section_label(draw, y, "Damage Breakdown")
    y += SECTION_LABEL_H
    _draw_damage_breakdown(draw, y, ctx)
    y += DAMAGE_BAR_H + 22

    footer_text = (
        f"Ranks and Percentiles are calculated based among {tracked_total:,} player(s) this bot has looked up."
    )
    draw.text((MARGIN, y), footer_text, font=theme.body(13), fill=theme.MUTED_TEXT)

    legend_text = "meets expert requirements"
    legend_font = theme.body(13)
    legend_w, legend_h = text_size(draw, legend_text, legend_font)
    legend_star_r = 6
    legend_x = CANVAS_W - MARGIN - legend_w
    draw_star(draw, legend_x - legend_star_r - 8, y + legend_h / 2, legend_star_r, theme.GOLD)
    draw.text((legend_x, y), legend_text, font=legend_font, fill=theme.MUTED_TEXT)

    note_text = "I love love love Celybi <3"
    draw.text((MARGIN, y + 24), note_text, font=theme.label(13), fill=theme.ACCENT)

    return img
