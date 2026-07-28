"""Renders personal match history as a themed PNG card (same style as /bbastats)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PIL import Image, ImageDraw

from render import theme
from render.shapes import aa_line, aa_rounded_rectangle, draw_gradient_text, text_size

CANVAS_W = 720
MARGIN = 28
HEADER_H = 108
SUMMARY_H = 72
ROW_H = 92
ROW_GAP = 10
FOOTER_GAP = 20
FOOTER_LINE_H = 18


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
        # Accept both Z and offset forms.
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


def _draw_summary(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: float,
    totals: dict[str, int | None],
    count: int,
) -> None:
    box = (MARGIN, y, CANVAS_W - MARGIN, y + SUMMARY_H)
    aa_rounded_rectangle(img, box, radius=14, fill=theme.CARD_BG, outline=theme.BORDER, width=1)

    cells = [
        ("MATCHES", str(count)),
        ("K / A / D", f"{totals['k']}/{totals['a']}/{totals['d']}"),
        ("POINTS", str(totals["pts"])),
        ("ELO", f"{totals['elo']:+d}" if totals["elo_seen"] else "n/a"),
    ]
    cell_w = (CANVAS_W - 2 * MARGIN) / len(cells)
    for i, (label, value) in enumerate(cells):
        cx = MARGIN + cell_w * (i + 0.5)
        lw, _ = text_size(draw, label, theme.label(11))
        vw, _ = text_size(draw, value, theme.heading(20))
        draw.text((cx - lw / 2, y + 14), label, font=theme.label(11), fill=theme.MUTED_TEXT)
        value_fill = theme.MAIN if label != "ELO" else _elo_color(totals["elo"] if totals["elo_seen"] else None)
        if label == "ELO" and not totals["elo_seen"]:
            value_fill = theme.MUTED_TEXT
        draw.text((cx - vw / 2, y + 34), value, font=theme.heading(20), fill=value_fill)


def _draw_match_row(img: Image.Image, draw: ImageDraw.ImageDraw, y: float, index: int, match: dict[str, Any]) -> None:
    box = (MARGIN, y, CANVAS_W - MARGIN, y + ROW_H)
    aa_rounded_rectangle(img, box, radius=14, fill=theme.CARD_BG, outline=theme.BORDER, width=1)

    # Index pill
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
    kp = _as_int(match.get("killParticipation"))
    pts = _as_int(match.get("points"))
    score = _as_int(match.get("finalScore"))
    place = _as_int(match.get("placement"))
    elo = _as_int(match.get("eloDelta"))
    rounds = _as_int(match.get("roundsPlayed"))
    ppr = match.get("pointsPerRound") if isinstance(match.get("pointsPerRound"), list) else []

    if k is not None or a is not None or d is not None:
        combat = f"{k or 0}/{a or 0}/{d or 0} K/A/D"
    elif kp is not None:
        combat = f"{kp} KP"
    else:
        combat = "— KP"

    place_txt = f"#{place}" if place is not None else "—"
    score_txt = str(score) if score is not None else "—"
    pts_txt = str(pts) if pts is not None else "—"
    elo_txt = f"{elo:+d}" if elo is not None else "n/a"
    rounds_txt = f"{rounds}r" if rounds is not None else ""

    stats_line = f"{combat}   ·   {pts_txt} pts   ·   place {place_txt}   ·   score {score_txt}"
    if rounds_txt:
        stats_line += f"   ·   {rounds_txt}"
    draw.text((MARGIN + 18, y + 48), stats_line, font=theme.body(14), fill=theme.MUTED_TEXT)

    elo_font = theme.heading(18)
    elw, _ = text_size(draw, elo_txt, elo_font)
    draw.text(
        (CANVAS_W - MARGIN - 16 - elw, y + 46),
        elo_txt,
        font=elo_font,
        fill=_elo_color(elo),
    )

    if ppr:
        ppr_txt = "rounds: " + " · ".join(str(x) for x in ppr[:10])
        draw.text((MARGIN + 18, y + 70), ppr_txt, font=theme.body(12), fill=theme.MUTED_TEXT)
    else:
        draw.text((MARGIN + 18, y + 70), "rounds: —", font=theme.body(12), fill=theme.MUTED_TEXT)


def render_history_card(payload: dict[str, Any], count: int = 5) -> Image.Image:
    matches: list[dict[str, Any]] = list(payload.get("matches") or [])
    recent = matches[: max(1, min(10, count))]
    ign = str(payload.get("playerIgn") or "player")
    display_name = theme.DISPLAY_NAME_OVERRIDES.get(ign.lower(), ign)

    totals = {"k": 0, "a": 0, "d": 0, "pts": 0, "elo": 0, "elo_seen": 0}
    for m in recent:
        totals["k"] += _as_int(m.get("kills")) or 0
        totals["a"] += _as_int(m.get("assists")) or 0
        totals["d"] += _as_int(m.get("deaths")) or 0
        totals["pts"] += _as_int(m.get("points")) or 0
        elo = _as_int(m.get("eloDelta"))
        if elo is not None:
            totals["elo"] += elo
            totals["elo_seen"] += 1

    rows_h = len(recent) * ROW_H + max(len(recent) - 1, 0) * ROW_GAP if recent else 36
    canvas_h = HEADER_H + 12 + SUMMARY_H + 16 + rows_h + FOOTER_GAP + FOOTER_LINE_H + MARGIN

    img = Image.new("RGB", (CANVAS_W, canvas_h), theme.BACKGROUND)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, CANVAS_W, 6), fill=theme.ACCENT)

    title = "Match History"
    draw.text((MARGIN, 24), title, font=theme.heading(26), fill=theme.TEXT)

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
    draw.text((CANVAS_W - MARGIN - bw, 28), brand_text, font=brand_font, fill=theme.MAIN)
    period_brand = "PERSONAL"
    pbw, _ = text_size(draw, period_brand, theme.label(12))
    draw.text((CANVAS_W - MARGIN - pbw, 50), period_brand, font=theme.label(12), fill=theme.MUTED_TEXT)

    aa_line(img, (MARGIN, HEADER_H, CANVAS_W - MARGIN, HEADER_H), fill=theme.BORDER, width=1)

    y = HEADER_H + 12
    _draw_summary(img, draw, y, totals, len(recent))
    y += SUMMARY_H + 16

    if not recent:
        draw.text((MARGIN, y), "No recorded matches yet.", font=theme.body(15), fill=theme.MUTED_TEXT)
        y += 28
    else:
        for i, match in enumerate(recent, start=1):
            _draw_match_row(img, draw, y, i, match)
            y += ROW_H
            if i != len(recent):
                y += ROW_GAP

    y += FOOTER_GAP
    footer = "Recorded by battlebox-qol · uploaded to this bot"
    draw.text((MARGIN, y), footer, font=theme.body(13), fill=theme.MUTED_TEXT)

    return img
