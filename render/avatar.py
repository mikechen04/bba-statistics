"""Fetches and caches Minecraft player head renders from Crafatar."""
from __future__ import annotations

import io
import time

import requests
from PIL import Image

import config

_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
_memory_cache: dict[str, tuple[float, bytes]] = {}


# Crafatar is primary; mc-heads.net is a fallback in case Crafatar is briefly
# down (it has had intermittent outages), so cards don't degrade to a blank
# placeholder any time that one service hiccups.
_SOURCES = (
    lambda uuid, size: f"https://crafatar.com/avatars/{uuid}?size={size}&overlay",
    lambda uuid, size: f"https://mc-heads.net/avatar/{uuid}/{size}",
)


def _fetch_bytes(uuid: str, size: int) -> bytes:
    now = time.time()
    cache_key = f"{uuid}:{size}"
    cached = _memory_cache.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    cache_file = config.CACHE_DIR / f"avatar_{uuid}_{size}.png"
    if cache_file.exists() and now - cache_file.stat().st_mtime < _CACHE_TTL_SECONDS:
        data = cache_file.read_bytes()
        _memory_cache[cache_key] = (now, data)
        return data

    last_error: Exception | None = None
    for build_url in _SOURCES:
        try:
            response = requests.get(build_url(uuid, size), timeout=10)
            response.raise_for_status()
            data = response.content
            cache_file.write_bytes(data)
            _memory_cache[cache_key] = (now, data)
            return data
        except Exception as e:  # try the next source
            last_error = e
    raise last_error or RuntimeError("No avatar source available")


def get_avatar(uuid: str, size: int = 128) -> Image.Image:
    """Returns a square RGBA Minecraft head render for the given player UUID.

    Falls back to a flat placeholder if Crafatar is unreachable, so a card can
    still render even if the avatar service is briefly down.
    """
    try:
        data = _fetch_bytes(uuid, size)
        return Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size))
    except Exception:
        placeholder = Image.new("RGBA", (size, size), (223, 232, 244, 255))
        return placeholder
