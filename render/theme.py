"""Shared visual style constants and font helpers for rendered cards.

Dark-mode variant of the original style guide (kept easier on the eyes):
- Font: Lexend (bold headings, regular body).
- Main: dusty light blue #7EA6D4 (unchanged, reads well on dark backgrounds).
- Background: near-black instead of near-white.
- Text: near-white instead of near-black.
- Accent: soft blush pink #E8A9C0, still used sparingly for a single highlight/CTA.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont

from config import FONTS_DIR

MAIN = (126, 166, 212)        # #7EA6D4
TEXT = (240, 240, 240)        # near-white body/heading text
BACKGROUND = (18, 18, 20)     # near-black page background
ACCENT = (232, 169, 192)      # #E8A9C0

# Supporting neutrals derived from the palette, used for card chrome/borders.
WHITE = (255, 255, 255)
CARD_BG = (30, 31, 35)        # elevated dark surface for stat/party boxes
BORDER = (54, 56, 62)
MUTED_TEXT = (150, 155, 165)
MAIN_SOFT = (35, 48, 68)      # dark tint of MAIN, used for rank-badge backgrounds
ACCENT_SOFT = (58, 38, 46)    # dark tint of ACCENT, used sparingly
ACCENT_DARK = (240, 176, 198)  # bright shade of ACCENT for legible text on ACCENT_SOFT
GOLD = (223, 178, 84)         # muted gold, reserved for the "Expert LFG" merit star

# Special-cased name gradients (left -> right) for specific players, as a personal touch.
NAME_GRADIENTS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "imeowforpets": ((242, 170, 200), (150, 190, 232)),  # light pink -> light blue
    "ceiybi": ((196, 165, 227), (242, 170, 200)),        # light purple -> light pink
}

# Usernames that get a small heart drawn next to their name, as a personal touch.
HEART_USERNAMES: set[str] = {"ceiybi", "unravelingstasis"}

_FONT_PATH = FONTS_DIR / "Lexend-Variable.ttf"

# Named weights on the Lexend variable font's `wght` axis.
WEIGHT_REGULAR = 400
WEIGHT_MEDIUM = 500
WEIGHT_SEMIBOLD = 600
WEIGHT_BOLD = 700


@lru_cache(maxsize=64)
def font(size: int, weight: int = WEIGHT_REGULAR) -> ImageFont.FreeTypeFont:
    """Return a Lexend font at the given pixel size and variable-axis weight."""
    f = ImageFont.truetype(str(_FONT_PATH), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass  # Falls back to the font's default weight if variation axes are unsupported.
    return f


def heading(size: int) -> ImageFont.FreeTypeFont:
    return font(size, WEIGHT_BOLD)


def body(size: int) -> ImageFont.FreeTypeFont:
    return font(size, WEIGHT_REGULAR)


def label(size: int) -> ImageFont.FreeTypeFont:
    return font(size, WEIGHT_SEMIBOLD)
