"""Avatar fetching should pick up a changed Minecraft profile picture."""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import config
import render.avatar as avatar


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (*color, 255)).save(buf, format="PNG")
    return buf.getvalue()


class AvatarRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_cache = config.CACHE_DIR
        config.CACHE_DIR = Path(self._tmpdir.name)
        avatar._memory_cache.clear()

    def tearDown(self) -> None:
        config.CACHE_DIR = self._original_cache
        avatar._memory_cache.clear()
        self._tmpdir.cleanup()

    def test_fresh_fetch_ignores_stale_disk_cache(self) -> None:
        uuid = "abc-123"
        stale = _png_bytes((255, 0, 0))
        live = _png_bytes((0, 255, 0))
        cache_file = config.CACHE_DIR / f"avatar_{uuid}_16.png"
        cache_file.write_bytes(stale)

        response = Mock()
        response.content = live
        response.raise_for_status = Mock()

        with patch("render.avatar.requests.get", return_value=response) as get:
            image = avatar.get_avatar(uuid, size=16, fresh=True)

        get.assert_called()
        pixel = image.getpixel((0, 0))
        self.assertEqual(pixel[1], 255)
        self.assertEqual(pixel[0], 0)

    def test_memory_cache_is_skipped_when_fresh(self) -> None:
        uuid = "abc-123"
        first = _png_bytes((255, 0, 0))
        second = _png_bytes((0, 0, 255))

        def _response(data: bytes) -> Mock:
            response = Mock()
            response.content = data
            response.raise_for_status = Mock()
            return response

        with patch("render.avatar.requests.get", side_effect=[_response(first), _response(second)]) as get:
            avatar.get_avatar(uuid, size=16, fresh=True)
            image = avatar.get_avatar(uuid, size=16, fresh=True)

        self.assertEqual(get.call_count, 2)
        pixel = image.getpixel((0, 0))
        self.assertEqual(pixel[2], 255)
        self.assertEqual(pixel[0], 0)

    def test_offline_fallback_uses_last_saved_file(self) -> None:
        uuid = "abc-123"
        saved = _png_bytes((0, 128, 255))
        cache_file = config.CACHE_DIR / f"avatar_{uuid}_16.png"
        cache_file.write_bytes(saved)

        with patch("render.avatar.requests.get", side_effect=RuntimeError("down")):
            image = avatar.get_avatar(uuid, size=16, fresh=True)

        pixel = image.getpixel((0, 0))
        self.assertEqual(pixel[2], 255)
