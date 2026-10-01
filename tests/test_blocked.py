"""Blocked IGN lookups look like a misspelled name."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import config
import db.database as db
from cogs.common import UserFacingError, reject_blocked_username
from stats.derive import RAW_KEYS

DURING_S5 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _raw(**overrides: int) -> dict[str, int]:
    base = {key: 0 for key in RAW_KEYS}
    base.update(overrides)
    return base


class BlockedUsernameTests(unittest.TestCase):
    def test_chatsura_is_blocked_case_insensitive(self) -> None:
        self.assertTrue(config.is_blocked_username("CHATSURA"))
        self.assertTrue(config.is_blocked_username("chatsura"))
        self.assertTrue(config.is_blocked_username(" Chatsura "))
        self.assertFalse(config.is_blocked_username("larppickleman"))
        self.assertFalse(config.is_blocked_username(None))
        self.assertFalse(config.is_blocked_username(""))

    def test_reject_looks_like_a_misspell(self) -> None:
        with self.assertRaises(UserFacingError) as ctx:
            reject_blocked_username("CHATSURA")
        self.assertEqual(str(ctx.exception), "you mispelled their name dumbass")
        reject_blocked_username("someoneelse")


class BlockedStatsPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = config.DB_PATH
        config.DB_PATH = Path(self._tmpdir.name) / "test.sqlite3"
        self._original_now = db._now
        db._now = lambda: DURING_S5
        db.init_db()

    def tearDown(self) -> None:
        db._now = self._original_now
        config.DB_PATH = self._original_db
        self._tmpdir.cleanup()

    def test_track_skips_blocked_username(self) -> None:
        db.track_player_stats(
            "blocked",
            "CHATSURA",
            _raw(games_played=200, kills=80, games_won=90, rounds_played=400),
        )
        db.track_player_stats(
            "u1",
            "Player",
            _raw(games_played=120, kills=40, games_won=50, rounds_played=240),
        )

        self.assertEqual(db.get_player_raw("blocked")["games_played"], 0)
        names = {row["username"].lower() for row in db.all_raw_rows()}
        self.assertNotIn("chatsura", names)
        self.assertIn("player", names)

    def test_already_cached_blocked_name_is_hidden_from_boards(self) -> None:
        db.upsert_player_stats(
            "blocked",
            "CHATSURA",
            _raw(games_played=200, kills=80, games_won=90, rounds_played=400),
        )
        db.upsert_player_stats(
            "u1",
            "Player",
            _raw(games_played=120, kills=40, games_won=50, rounds_played=240),
        )

        names = {row["username"].lower() for row in db.all_raw_rows()}
        self.assertNotIn("chatsura", names)
        board = db.compute_leaderboard("games_played")
        self.assertTrue(all(entry["username"].lower() != "chatsura" for entry in board))


if __name__ == "__main__":
    unittest.main()
