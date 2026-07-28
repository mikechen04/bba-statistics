"""Renders personal match history as a themed PNG card (same style as /bbastats)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PIL import Image, ImageDraw

from render import theme
from render.shapes import aa_line, aa_rounded_rectangle, draw_gradient_text, text_size

CANVAS_W = 720
MARGIN = 28
HEADER_H = 96
ROW_H = 92
ROW_GAP = 10


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _fmt_ended(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "unknown time"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%b %d · %H:%M UTC")
    except Exception:
        return text.replace("T", " ").replace("Z", " UTC")[:22]


def _mode_label(mode: Any) -> str:
    raw = str(mode or "BATTLE_BOX").replace("_", " ").title()
    if "Arena" in raw:
        return "Arena"
    if "Battle Box" in raw:
        return "Classic"
    return raw


def _elo_color(delta: int | None) -> tuple[int, int, int]:
    if delta is None:
        return theme.MUTED_TEXT
    if delta > 0:
        return (120, 196, 150)
    if delta < 0:
        return (220, 120, 130)
    return theme.MUTED_TEXT


def _scoreline(match: dict[str, Any]) -> str:
    line = match.get("scoreline")
    if isinstance(line, str) and line.strip():
        return line.strip()
    us = _as_int(match.get("roundsWonUs"))
    them = _as_int(match.get("roundsWonThem"))
    if us is not None and them is not None:
        return f"{us}-{them}"
    return "—"


def _draw_match_row(img: Image.Image, draw: ImageDraw.ImageDraw, y: float, index: int, match: dict[str, Any]) -> None:
    box = (MARGIN, y, CANVAS_W - MARGIN, y + ROW_H)
    aa_rounded_rectangle(img, box, radius=14, fill=theme.CARD_BG, outline=theme.BORDER, width=1)

    pill_text = f"#{index}"
    pill_font = theme.label(14)
    ink_left, ink_top, ink_right, ink_bottom = draw.textbbox((0, 0), pill_text, font=pill_font)
    pw, ph = ink_right - ink_left, ink_bottom - ink_top
    pad_x, pad_y = 10, 5
    pill = (MARGIN + 14, y + 14, MARGIN + 14 + pw + 2 * pad_x, y + 14 + ph + 2 * pad_y)
    aa_rounded_rectangle(img, pill, radius=(ph + 2 * pad_y) / 2, fill=theme.MAIN_SOFT)
    draw.text((pill[0] + pad_x - ink_left, pill[1] + pad_y - ink_top), pill_text, font=pill_font, fill=theme.MAIN)

    map_name = str(match.get("mapName") or "Unknown map")
    mode = _mode_label(match.get("mode"))
    title = f"{map_name}  ·  {mode}"
    draw.text((MARGIN + 14 + pw + 2 * pad_x + 12, y + 16), title, font=theme.label(17), fill=theme.TEXT)

    ended = _fmt_ended(match.get("endedAt"))
    ew, _ = text_size(draw, ended, theme.body(13))
    draw.text((CANVAS_W - MARGIN - 16 - ew, y + 18), ended, font=theme.body(13), fill=theme.MUTED_TEXT)

    k = _as_int(match.get("kills"))
    a = _as_int(match.get("assists"))
    d = _as_int(match.get("deaths"))
    # Legacy fallback: old rows only had combined KP.
    if k is None and a is None and d is None:
        kp = _as_int(match.get("killParticipation"))
        combat = f"{kp} KP" if kp is not None else "0/0/0 K/D/A"
    else:
        combat = f"{k or 0}/{d or 0}/{a or 0} K/D/A"

    pts = _as_int(match.get("points"))
    # Old JSON wrongly put personal points in finalScore — only use if points missing
    # and scoreline is absent (so we don't show a round score as "pts").
    if pts is None and not match.get("scoreline"):
        legacy = _as_int(match.get("finalScore"))
        if legacy is not None and legacy <= 30:
            pts = legacy

    pts_txt = f"{pts} pts" if pts is not None else "— pts"
    score_txt = _scoreline(match)
    elo = _as_int(match.get("eloDelta"))
    elo_txt = f"{elo:+d}" if elo is not None else "n/a"

    stats_line = f"{combat}   ·   {pts_txt}   ·   {score_txt}"
    draw.text((MARGIN + 18, y + 48), stats_line, font=theme.body(14), fill=theme.MUTED_TEXT)

    elo_font = theme.heading(18)
    elw, _ = text_size(draw, elo_txt, elo_font)
    draw.text(
        (CANVAS_W - MARGIN - 16 - elw, y + 46),
        elo_txt,
        font=elo_font,
        fill=_elo_color(elo),
    )

    ppr = match.get("pointsPerRound") if isinstance(match.get("pointsPerRound"), list) else []
    if ppr:
        ppr_txt = "pts/round: " + " · ".join(str(x) for x in ppr[:10])
        draw.text((MARGIN + 18, y + 70), ppr_txt, font=theme.body(12), fill=theme.MUTED_TEXT)
    else:
        place = _as_int(match.get("placement"))
        place_txt = f"placement #{place}" if place is not None else ""
        draw.text((MARGIN + 18, y + 70), place_txt or " ", font=theme.body(12), fill=theme.MUTED_TEXT)


def render_history_card(payload: dict[str, Any], count: int = 5) -> Image.Image:
    matches: list[dict[str, Any]] = list(payload.get("matches") or [])
    recent = matches[: max(1, min(10, count))]
    ign = str(payload.get("playerIgn") or "player")
    display_name = theme.DISPLAY_NAME_OVERRIDES.get(ign.lower(), ign)

    rows_h = len(recent) * ROW_H + max(len(recent) - 1, 0) * ROW_GAP if recent else 36
    canvas_h = HEADER_H + 14 + rows_h + MARGIN

    img = Image.new("RGB", (CANVAS_W, canvas_h), theme.BACKGROUND)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, CANVAS_W, 6), fill=theme.ACCENT)

    draw.text((MARGIN, 24), "Match History", font=theme.heading(26), fill=theme.TEXT)

    name_font = theme.label(16)
    name_y = 58
    gradient = theme.NAME_GRADIENTS.get(display_name.lower())
    if gradient:
        draw_gradient_text(img, (MARGIN, name_y), display_name, name_font, *gradient)
    else:
        draw.text((MARGIN, name_y), display_name, font=name_font, fill=theme.TEXT)

    _, _, name_right, _ = draw.textbbox((MARGIN, name_y), display_name, font=name_font)
    subtitle = f"  ·  last {len(recent)} match{'es' if len(recent) != 1 else ''}"
    draw.text((name_right, name_y), subtitle, font=theme.body(14), fill=theme.MUTED_TEXT)

    brand_text = "BBA STATS"
    brand_font = theme.heading(16)
    bw, _ = text_size(draw, brand_text, brand_font)
    draw.text((CANVAS_W - MARGIN - bw, 34), brand_text, font=brand_font, fill=theme.MAIN)

    aa_line(img, (MARGIN, HEADER_H, CANVAS_W - MARGIN, HEADER_H), fill=theme.BORDER, width=1)

    y = HEADER_H + 14
    if not recent:
        draw.text((MARGIN, y), "No recorded matches yet.", font=theme.body(15), fill=theme.MUTED_TEXT)
    else:
        for i, match in enumerate(recent, start=1):
            _draw_match_row(img, draw, y, i, match)
            y += ROW_H
            if i != len(recent):
                y += ROW_GAP

    return img
