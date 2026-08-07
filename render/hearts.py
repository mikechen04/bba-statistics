"""Purple heart badge drawn next to selected usernames on rendered cards."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image

from render import theme
from render.shapes import _paste_rgba

_HEART_PATH = Path(__file__).resolve().parent / "assets" / "purple_heart.png"


@lru_cache(maxsize=8)
def purple_heart(size: int) -> Image.Image:
    """Load and cache the purple heart asset at the requested pixel size."""
    if not _HEART_PATH.is_file():
        raise FileNotFoundError(f"Missing purple heart asset: {_HEART_PATH}")
    return Image.open(_HEART_PATH).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def has_name_heart(username: str | None) -> bool:
    if not username:
        return False
    return username.strip().lower() in theme.HEART_USERNAMES


def paste_name_heart(
    image: Image.Image,
    left_x: float,
    center_y: float,
    *,
    size: int = 22,
    gap: int = 8,
) -> int:
    """Paste the purple heart to the right of a name. Returns the x just past the heart."""
    # Copy so a shared cache entry is never used as both source and mask in-place.
    heart = purple_heart(size).copy()
    x = int(round(left_x + gap))
    y = int(round(center_y - size / 2))
    _paste_rgba(image, heart, (x, y))
    return x + size
