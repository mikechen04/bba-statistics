"""Renders the /bbaradar result: side panels + overlapping radar chart."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from render import theme
from render.avatar import get_avatar
from render.shapes import rounded_crop, text_size
from stats.radar import RADAR_AXES, panel_stats, radar_scores

CANVAS_W = 1000
MARGIN = 28
HEADER_H = 56
PANEL_H = 156
PANEL_GAP = 16
CHART_TOP_PAD = 18
CHART_SIZE = 420
LEGEND_H = 88
FOOTER_GAP = 18


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
    draw.rounded_rectangle(box, radius=14, fill=theme.CARD_BG, outline=theme.BORDER, width=1)

    # Color tick matching this player's radar polygon.
    draw.rounded_rectangle((x0 + 16, y0 + 18, x0 + 20, y0 + 36), radius=2, fill=player.color)

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
) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    draw = ImageDraw.Draw(img)
    n = len(RADAR_AXES)

    # Fills first (very light) so grid lines drawn afterward stay readable.
    for player in players:
        scores = radar_scores(player.raw)
        pts = [
            _axis_point(cx, cy, radius, i, n, scores[axis.key])
            for i, axis in enumerate(RADAR_AXES)
        ]
        odraw.polygon(pts, fill=(*player.color, 18))

    img.alpha_composite(overlay)

    # Grid rings + spokes on top of the fills.
    for ring in (20, 40, 60, 80, 100):
        pts = [_axis_point(cx, cy, radius, i, n, float(ring)) for i in range(n)]
        draw.line(pts + [pts[0]], fill=theme.BORDER, width=1)
        if ring < 100:
            label = str(ring)
            lf = theme.body(11)
            lx, ly = _axis_point(cx, cy, radius, 0, n, float(ring))
            draw.text((lx - 22, ly - 6), label, font=lf, fill=theme.MUTED_TEXT)

    for i, axis in enumerate(RADAR_AXES):
        tip = _axis_point(cx, cy, radius, i, n, 100.0)
        draw.line((cx, cy, tip[0], tip[1]), fill=theme.BORDER, width=1)

        angle = -math.pi / 2 + (2 * math.pi * i / n)
        label_r = radius + 38
        lx = cx + label_r * math.cos(angle)
        ly = cy + label_r * math.sin(angle)
        font = theme.label(13)
        tw, th = text_size(draw, axis.label, font)
        draw.text((lx - tw / 2, ly - th / 2), axis.label, font=font, fill=theme.MUTED_TEXT)

    # Polygon outlines + dots on top of everything.
    for player in players:
        scores = radar_scores(player.raw)
        pts = [
            _axis_point(cx, cy, radius, i, n, scores[axis.key])
            for i, axis in enumerate(RADAR_AXES)
        ]
        draw.line(pts + [pts[0]], fill=player.color, width=3)
        for px, py in pts:
            r = 4.5
            draw.ellipse((px - r, py - r, px + r, py + r), fill=player.color)

def render_radar_card(players: list[RadarPlayer]) -> Image.Image:
    """`players` must be length 1 or 2. Colors are assigned by the caller."""
    if not players or len(players) > 2:
        raise ValueError("render_radar_card expects 1 or 2 players")

    canvas_h = (
        HEADER_H
        + PANEL_H
        + CHART_TOP_PAD
        + CHART_SIZE
        + 56  # room for axis labels outside the chart
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
    if len(players) == 1:
        panel_w = CANVAS_W - 2 * MARGIN
        _draw_player_panel(img, draw, (MARGIN, panel_y, MARGIN + panel_w, panel_y + PANEL_H), players[0])
    else:
        panel_w = (CANVAS_W - 2 * MARGIN - PANEL_GAP) // 2
        _draw_player_panel(img, draw, (MARGIN, panel_y, MARGIN + panel_w, panel_y + PANEL_H), players[0])
        x1 = MARGIN + panel_w + PANEL_GAP
        _draw_player_panel(img, draw, (x1, panel_y, x1 + panel_w, panel_y + PANEL_H), players[1])

    # Radar chart centered below the panels.
    chart_cy = panel_y + PANEL_H + CHART_TOP_PAD + CHART_SIZE // 2 + 10
    chart_cx = CANVAS_W // 2
    chart_r = CHART_SIZE // 2 - 8
    _draw_radar(img, chart_cx, chart_cy, chart_r, players)

    # Legend / definitions.
    legend_y = chart_cy + chart_r + 48
    legend_font = theme.body(12)
    blurbs = [f"{axis.label} = {axis.blurb}" for axis in RADAR_AXES]
    # Two lines of three.
    line1 = "   ·   ".join(blurbs[:3])
    line2 = "   ·   ".join(blurbs[3:])
    for i, line in enumerate((line1, line2)):
        tw, _ = text_size(draw, line, legend_font)
        draw.text(((CANVAS_W - tw) / 2, legend_y + i * 18), line, font=legend_font, fill=theme.MUTED_TEXT)

    # Color key when comparing two players.
    if len(players) == 2:
        key_y = legend_y + 44
        kx = MARGIN
        for player in players:
            draw.ellipse((kx, key_y + 2, kx + 10, key_y + 12), fill=player.color)
            name = _display_name(player.username)
            draw.text((kx + 16, key_y), name, font=theme.label(13), fill=theme.TEXT)
            kx += text_size(draw, name, theme.label(13))[0] + 40

    return img.convert("RGB")
