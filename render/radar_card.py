"""Renders the /bbaradar result: side panels + overlapping radar chart."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from render import theme
from render.avatar import get_avatar
from render.shapes import aa_ellipse, aa_line, aa_polygon, aa_rounded_rectangle, rounded_crop, text_size
from stats.radar import RADAR_AXES, panel_stats, radar_scores

CANVAS_W = 1000
MARGIN = 28
HEADER_H = 56
PANEL_H = 156
PANEL_GAP = 16
# Space above the hex tip reserved for the top axis label ("Fragging"), so it
# never collides with the player stat panel(s).
LABEL_OUTSET = 44
CHART_TOP_GAP = 40
CHART_TOP_PAD = LABEL_OUTSET + CHART_TOP_GAP
CHART_SIZE = 400
CHART_BOTTOM_PAD = LABEL_OUTSET + 28
LEGEND_H = 88
FOOTER_GAP = 18
RADAR_AA_SCALE = 6


@dataclass
class RadarPlayer:
    username: str
    uuid: str
    raw: dict
    color: tuple[int, int, int]


def _display_name(username: str) -> str:
    return theme.DISPLAY_NAME_OVERRIDES.get(username.lower(), username)


def _axis_point(cx: float, cy: float, radius: float, index: int, total: int, score: float) -> tuple[float, float]:
    # Start at top (-90°) and go clockwise so the layout reads naturally.
    angle = -math.pi / 2 + (2 * math.pi * index / total)
    r = radius * (score / 100.0)
    return cx + r * math.cos(angle), cy + r * math.sin(angle)


def _draw_player_panel(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    player: RadarPlayer,
) -> None:
    x0, y0, x1, y1 = box
    aa_rounded_rectangle(img, box, radius=14, fill=theme.CARD_BG, outline=theme.BORDER, width=1, scale=5)

    # Color tick matching this player's radar polygon.
    aa_rounded_rectangle(img, (x0 + 16, y0 + 18, x0 + 20, y0 + 36), radius=2, fill=player.color, scale=5)

    avatar = rounded_crop(get_avatar(player.uuid, size=36), radius=8)
    img.paste(avatar, (x0 + 30, y0 + 16), avatar)

    name = _display_name(player.username)
    name_font = theme.heading(18)
    draw.text((x0 + 78, y0 + 20), name, font=name_font, fill=theme.TEXT)

    stats = panel_stats(player.raw)
    cols = 3
    pad_x = 20
    inner_w = x1 - x0 - 2 * pad_x
    col_w = inner_w / cols
    row_h = 44
    grid_y = y0 + 68
    label_font = theme.label(11)
    value_font = theme.heading(17)

    for i, (label, value) in enumerate(stats):
        col = i % cols
        row = i // cols
        cell_left = x0 + pad_x + col * col_w
        cell_cx = cell_left + col_w / 2
        sy = grid_y + row * row_h

        lw, _ = text_size(draw, label, label_font)
        vw, _ = text_size(draw, value, value_font)
        draw.text((cell_cx - lw / 2, sy), label, font=label_font, fill=theme.MUTED_TEXT)
        draw.text((cell_cx - vw / 2, sy + 16), value, font=value_font, fill=theme.TEXT)


def _draw_radar(
    img: Image.Image,
    cx: int,
    cy: int,
    radius: int,
    players: list[RadarPlayer],
    label_min_y: float,
    label_max_y: float,
) -> None:
    draw = ImageDraw.Draw(img)
    n = len(RADAR_AXES)

    # Fills first (light), then outlines, then grid on top so rings stay visible.
    for player in players:
        scores = radar_scores(player.raw)
        pts = [
            _axis_point(cx, cy, radius, i, n, scores[axis.key])
            for i, axis in enumerate(RADAR_AXES)
        ]
        aa_polygon(img, pts, fill=(*player.color, 22), scale=RADAR_AA_SCALE)

    for player in players:
        scores = radar_scores(player.raw)
        pts = [
            _axis_point(cx, cy, radius, i, n, scores[axis.key])
            for i, axis in enumerate(RADAR_AXES)
        ]
        aa_line(img, pts + [pts[0]], fill=player.color, width=3, scale=RADAR_AA_SCALE)
        for px, py in pts:
            r = 4.5
            aa_ellipse(img, (px - r, py - r, px + r, py + r), fill=player.color, scale=RADAR_AA_SCALE)

    # Grid rings + spokes drawn last so fills never hide them.
    for ring in (20, 40, 60, 80, 100):
        pts = [_axis_point(cx, cy, radius, i, n, float(ring)) for i in range(n)]
        aa_line(img, pts + [pts[0]], fill=theme.BORDER, width=1, scale=RADAR_AA_SCALE)
        if ring < 100:
            label = str(ring)
            lf = theme.body(11)
            lx, ly = _axis_point(cx, cy, radius, 0, n, float(ring))
            draw.text((lx - 22, ly - 6), label, font=lf, fill=theme.MUTED_TEXT)

    for i, axis in enumerate(RADAR_AXES):
        tip = _axis_point(cx, cy, radius, i, n, 100.0)
        aa_line(img, (cx, cy, tip[0], tip[1]), fill=theme.BORDER, width=1, scale=RADAR_AA_SCALE)

        angle = -math.pi / 2 + (2 * math.pi * i / n)
        lx = cx + (radius + LABEL_OUTSET) * math.cos(angle)
        ly = cy + (radius + LABEL_OUTSET) * math.sin(angle)
        font = theme.label(13)
        tw, th = text_size(draw, axis.label, font)
        text_y = ly - th / 2
        text_y = max(label_min_y, min(label_max_y - th, text_y))
        text_x = lx - tw / 2
        text_x = max(MARGIN, min(CANVAS_W - MARGIN - tw, text_x))
        draw.text((text_x, text_y), axis.label, font=font, fill=theme.MUTED_TEXT)


def render_radar_card(players: list[RadarPlayer]) -> Image.Image:
    """`players` must be length 1 or 2. Colors are assigned by the caller."""
    if not players or len(players) > 2:
        raise ValueError("render_radar_card expects 1 or 2 players")

    chart_r = CHART_SIZE // 2
    canvas_h = (
        HEADER_H
        + 4
        + PANEL_H
        + CHART_TOP_PAD
        + CHART_SIZE
        + CHART_BOTTOM_PAD
        + LEGEND_H
        + FOOTER_GAP
        + MARGIN
    )

    img = Image.new("RGBA", (CANVAS_W, canvas_h), (*theme.BACKGROUND, 255))
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, CANVAS_W, 6), fill=theme.ACCENT)

    title = "Battle Box Arena · Radar"
    draw.text((MARGIN, 22), title, font=theme.heading(22), fill=theme.TEXT)
    brand = "BBA STATS"
    bw, _ = text_size(draw, brand, theme.heading(16))
    draw.text((CANVAS_W - MARGIN - bw, 26), brand, font=theme.heading(16), fill=theme.MAIN)

    # Player panels.
    panel_y = HEADER_H + 4
    panel_bottom = panel_y + PANEL_H
    if len(players) == 1:
        panel_w = CANVAS_W - 2 * MARGIN
        _draw_player_panel(img, draw, (MARGIN, panel_y, MARGIN + panel_w, panel_bottom), players[0])
    else:
        panel_w = (CANVAS_W - 2 * MARGIN - PANEL_GAP) // 2
        _draw_player_panel(img, draw, (MARGIN, panel_y, MARGIN + panel_w, panel_bottom), players[0])
        x1 = MARGIN + panel_w + PANEL_GAP
        _draw_player_panel(img, draw, (x1, panel_y, x1 + panel_w, panel_bottom), players[1])

    # Hex tip sits CHART_TOP_PAD below the panel so "Fragging" fits in the gap.
    chart_cy = panel_bottom + CHART_TOP_PAD + chart_r
    chart_cx = CANVAS_W // 2
    legend_y = chart_cy + chart_r + CHART_BOTTOM_PAD

    _draw_radar(
        img,
        chart_cx,
        chart_cy,
        chart_r,
        players,
        label_min_y=panel_bottom + 18,
        label_max_y=legend_y - 8,
    )

    # Legend / definitions.
    legend_font = theme.body(12)
    blurbs = [f"{axis.label} = {axis.blurb}" for axis in RADAR_AXES]
    line1 = "   ·   ".join(blurbs[:3])
    line2 = "   ·   ".join(blurbs[3:])
    for i, line in enumerate((line1, line2)):
        tw, _ = text_size(draw, line, legend_font)
        draw.text(((CANVAS_W - tw) / 2, legend_y + i * 18), line, font=legend_font, fill=theme.MUTED_TEXT)

    # Color key when comparing two players — centered under the chart.
    if len(players) == 2:
        key_font = theme.label(13)
        gap = 28
        names = [_display_name(p.username) for p in players]
        widths = [10 + 8 + text_size(draw, name, key_font)[0] for name in names]
        total_w = sum(widths) + gap * (len(players) - 1)
        kx = (CANVAS_W - total_w) / 2
        key_y = legend_y + 44
        for player, name, entry_w in zip(players, names, widths):
            aa_ellipse(img, (kx, key_y + 2, kx + 10, key_y + 12), fill=player.color, scale=5)
            draw.text((kx + 18, key_y), name, font=key_font, fill=theme.TEXT)
            kx += entry_w + gap

    return img.convert("RGB")
