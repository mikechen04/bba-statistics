"""Renders the /bbaparty result as a PNG card (only used when the player IS in a party)."""
from __future__ import annotations

from PIL import Image, ImageDraw

from render import theme
from render.avatar import get_avatar
from render.shapes import rounded_crop, text_size

CANVAS_W = 640
MARGIN = 28
ROW_H = 76
ROW_GAP = 12
HEADER_H = 88


def render_party_card(leader: dict, members: list[dict]) -> Image.Image:
    """`leader` and `members` are dicts with `uuid` and `username` keys.
    `members` should include the leader; they'll be shown with a crown badge.
    """
    row_count = len(members)
    canvas_h = HEADER_H + row_count * ROW_H + max(row_count - 1, 0) * ROW_GAP + MARGIN

    img = Image.new("RGB", (CANVAS_W, canvas_h), theme.BACKGROUND)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, CANVAS_W, 6), fill=theme.ACCENT)

    draw.text((MARGIN, 26), "Party", font=theme.heading(28), fill=theme.TEXT)
    subtitle = f"{row_count} member{'s' if row_count != 1 else ''}"
    sw, _ = text_size(draw, subtitle, theme.body(15))
    draw.text((CANVAS_W - MARGIN - sw, 34), subtitle, font=theme.body(15), fill=theme.MUTED_TEXT)

    draw.line((MARGIN, HEADER_H, CANVAS_W - MARGIN, HEADER_H), fill=theme.BORDER, width=1)

    avatar_size = 48
    y = HEADER_H + 14
    leader_uuid = leader.get("uuid") if leader else None

    for member in members:
        box = (MARGIN, y, CANVAS_W - MARGIN, y + ROW_H)
        draw.rounded_rectangle(box, radius=14, fill=theme.CARD_BG, outline=theme.BORDER, width=1)

        avatar = rounded_crop(get_avatar(member["uuid"], size=avatar_size), radius=10)
        avatar_pos = (MARGIN + 14, y + (ROW_H - avatar_size) // 2)
        img.paste(avatar, avatar_pos, avatar)

        name_x = avatar_pos[0] + avatar_size + 16
        is_leader = leader_uuid is not None and member["uuid"] == leader_uuid
        name_font = theme.label(19)
        draw.text((name_x, y + ROW_H // 2 - 12), member["username"], font=name_font, fill=theme.TEXT)

        if is_leader:
            badge_text = "LEADER"
            bf = theme.label(12)
            bw, bh = text_size(draw, badge_text, bf)
            pad_x, pad_y = 9, 4
            badge_box = (
                CANVAS_W - MARGIN - 14 - bw - 2 * pad_x,
                y + ROW_H // 2 - (bh + 2 * pad_y) // 2,
                CANVAS_W - MARGIN - 14,
                y + ROW_H // 2 + (bh + 2 * pad_y) // 2,
            )
            draw.rounded_rectangle(badge_box, radius=(bh + 2 * pad_y) // 2, fill=theme.ACCENT_SOFT)
            draw.text((badge_box[0] + pad_x, badge_box[1] + pad_y - 1), badge_text, font=bf, fill=theme.ACCENT_DARK)

        y += ROW_H + ROW_GAP

    return img
