"""Custom /bbastats name colors (solid fill, stats card only)."""
from __future__ import annotations

import db.database as db
from render import theme

_NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "purple": (196, 165, 227),
    "pink": (242, 170, 200),
    "blue": (150, 190, 232),
    "gold": theme.GOLD,
    "white": theme.TEXT,
    "red": (240, 120, 120),
    "green": (120, 196, 150),
    "orange": (240, 180, 120),
}

_CLEAR_TOKENS = frozenset({"clear", "none", "remove", "reset", "default"})


def named_color_choices() -> str:
    return ", ".join(sorted(_NAMED_COLORS))


def parse_color(value: str) -> tuple[int, int, int] | None | str:
    """Parse a color string. Returns RGB, None if clear, or an error message."""
    raw = value.strip()
    if not raw:
        return "color can't be empty"

    lowered = raw.lower()
    if lowered in _CLEAR_TOKENS:
        return None

    if lowered in _NAMED_COLORS:
        return _NAMED_COLORS[lowered]

    if raw.startswith("#"):
        hex_part = raw[1:]
        if len(hex_part) == 3 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
            hex_part = "".join(c * 2 for c in hex_part)
        if len(hex_part) == 6 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
            return (
                int(hex_part[0:2], 16),
                int(hex_part[2:4], 16),
                int(hex_part[4:6], 16),
            )
        return "invalid hex — use #RRGGBB or #RGB"

    parts = [p.strip() for p in raw.replace(" ", ",").split(",") if p.strip()]
    if len(parts) == 3:
        try:
            rgb = tuple(int(p) for p in parts)
        except ValueError:
            return "rgb values must be numbers"
        if any(c < 0 or c > 255 for c in rgb):
            return "rgb values must be 0-255"
        return rgb

    return f"unknown color — try a name ({named_color_choices()}), #hex, or r,g,b"


def bbastats_name_color(username: str | None) -> tuple[int, int, int] | None:
    """Resolved solid name color for /bbastats. DB overrides beat theme defaults."""
    if not username:
        return None
    key = username.lower()
    stored = db.get_bbastats_name_color(key)
    if stored is not None:
        return stored
    return theme.BBASTATS_NAME_COLORS.get(key)
