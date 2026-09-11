"""Fetches Minecraft player head renders, preferring a live skin over a stale cache."""
from __future__ import annotations

import io
import time

import requests
from PIL import Image

import config

# Only reused inside a short burst (same card rendering the same UUID twice, or
# back-to-back commands). A long TTL used to keep old skins on the card for hours
# after a player changed their Minecraft profile picture.
_MEMORY_TTL_SECONDS = 30
_memory_cache: dict[str, tuple[float, bytes]] = {}

_FETCH_HEADERS = {
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": config.MCC_USER_AGENT,
}

# mc-heads.net picks up Mojang skin changes within about a minute; Crafatar is
# the fallback if that host is down. Both include the hat/overlay layer.
_SOURCES = (
    lambda uuid, size: f"https://mc-heads.net/avatar/{uuid}/{size}",
    lambda uuid, size: f"https://crafatar.com/avatars/{uuid}?size={size}&overlay",
)


def _cache_key(uuid: str, size: int) -> str:
    return f"{uuid}:{size}"


def _cache_file(uuid: str, size: int):
    return config.CACHE_DIR / f"avatar_{uuid}_{size}.png"


def invalidate_avatar(uuid: str) -> None:
    """Drop in-memory heads for this player so the next render fetches a live skin.

    The on-disk copy is left in place as a last-known-good fallback if every
    avatar host is down.
    """
    prefix = f"{uuid}:"
    for key in [k for k in _memory_cache if k.startswith(prefix)]:
        _memory_cache.pop(key, None)


def _fetch_bytes(uuid: str, size: int) -> bytes:
    now = time.time()
    cache_key = _cache_key(uuid, size)
    cached = _memory_cache.get(cache_key)
    if cached and now - cached[0] < _MEMORY_TTL_SECONDS:
        return cached[1]

    cache_file = _cache_file(uuid, size)
    last_error: Exception | None = None
    for build_url in _SOURCES:
        try:
            response = requests.get(build_url(uuid, size), timeout=10, headers=_FETCH_HEADERS)
            response.raise_for_status()
            data = response.content
            cache_file.write_bytes(data)
            _memory_cache[cache_key] = (now, data)
            return data
        except Exception as e:  # try the next source
            last_error = e

    # Sources are down: reuse the last good file so the card still renders.
    if cache_file.exists():
        data = cache_file.read_bytes()
        _memory_cache[cache_key] = (now, data)
        return data
    raise last_error or RuntimeError("No avatar source available")


def get_avatar(uuid: str, size: int = 128, *, fresh: bool = False) -> Image.Image:
    """Returns a square RGBA Minecraft head render for the given player UUID.

    `fresh=True` drops any cached copy first so a newly changed Minecraft
    profile picture shows up on the next card. Falls back to a flat
    placeholder if every avatar host is unreachable.
    """
    if fresh:
        invalidate_avatar(uuid)
    try:
        data = _fetch_bytes(uuid, size)
        return Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size))
    except Exception:
        placeholder = Image.new("RGBA", (size, size), (223, 232, 244, 255))
        return placeholder
