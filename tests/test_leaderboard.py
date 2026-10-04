"""/bbalb total deaths ranks most deaths first and is easy to find."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import config
import db.database as db
from cogs.leaderboard import matching_leaderboard_stats
from stats.derive import METRICS, RAW_KEYS

DURING_S5 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _raw(**overrides: int) -> dict[str, int]:
    base = {key: 0 for key in RAW_KEYS}
    base.update(overrides)
    return base


class TotalDeathsLeaderboardTests(unittest.TestCase):
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

    def test_total_deaths_is_a_bbalb_stat(self) -> None:
        self.assertIn("total_deaths", METRICS)
        self.assertEqual(METRICS["total_deaths"].label, "Total Deaths")
        self.assertIn("total_deaths", matching_leaderboard_stats(""))
        self.assertEqual(matching_leaderboard_stats("deaths")[0], "total_deaths")
        self.assertEqual(matching_leaderboard_stats("total deaths")[0], "total_deaths")

    def test_total_deaths_board_ranks_most_deaths_first(self) -> None:
        db.track_player_stats(
            "low",
            "LowDeaths",
            _raw(games_played=120, deaths=10, kills=80, games_won=50, rounds_played=240),
        )
        db.track_player_stats(
            "mid",
            "MidDeaths",
            _raw(games_played=120, deaths=40, kills=80, games_won=50, rounds_played=240),
        )
        db.track_player_stats(
            "high",
            "HighDeaths",
            _raw(games_played=120, deaths=90, kills=80, games_won=50, rounds_played=240),
        )

        board = db.compute_leaderboard("total_deaths", config.LIFETIME_KEY)
        self.assertEqual([row["username"] for row in board], ["HighDeaths", "MidDeaths", "LowDeaths"])
        self.assertEqual([row["value"] for row in board], [90, 40, 10])

    def test_stats_card_still_treats_fewer_deaths_as_better(self) -> None:
        self.assertEqual(METRICS["total_deaths"].direction, "asc")
        db.track_player_stats(
            "low",
            "LowDeaths",
            _raw(games_played=120, deaths=10, kills=80, games_won=50, rounds_played=240),
        )
        db.track_player_stats(
            "high",
            "HighDeaths",
            _raw(games_played=120, deaths=90, kills=80, games_won=50, rounds_played=240),
        )
        ranks = db.compute_percentiles("low", config.LIFETIME_KEY)
        self.assertEqual(ranks["total_deaths"]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
