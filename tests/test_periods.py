"""Period windows: Season 4 freeze, S4 Off-Season, and Season 5 deltas."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import config
import db.database as db
from stats.derive import RAW_KEYS

DURING_S4 = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
AFTER_S4 = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)  # 8:00 AM Eastern
BEFORE_S4 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
DURING_OFFSEASON = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
AFTER_S5 = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)  # ~2 hours after 08:09 UTC


def _raw(**overrides: int) -> dict[str, int]:
    base = {key: 0 for key in RAW_KEYS}
    base.update(overrides)
    return base


class PeriodConfigTests(unittest.TestCase):
    def test_offseason_starts_when_season4_ends(self) -> None:
        self.assertEqual(config.next_period(config.SEASON4_KEY), config.S4_OFFSEASON)
        self.assertEqual(config.previous_period(config.S4_OFFSEASON_KEY), config.SEASON4)
        self.assertEqual(config.SEASON4.end_at, config.S4_OFFSEASON.start_at)

    def test_season5_starts_when_offseason_ends(self) -> None:
        self.assertEqual(config.next_period(config.S4_OFFSEASON_KEY), config.SEASON5)
        self.assertEqual(config.previous_period(config.SEASON5_KEY), config.S4_OFFSEASON)
        self.assertEqual(config.S4_OFFSEASON.end_at, config.SEASON5.start_at)
        self.assertIsNone(config.SEASON5.end_at)

    def test_cutoff_is_6am_eastern_on_sep_8(self) -> None:
        start = config.S4_OFFSEASON_START_AT.astimezone(timezone.utc)
        self.assertEqual(start, datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc))

    def test_season5_starts_at_0809_utc_on_sep_22(self) -> None:
        start = config.SEASON5_START_AT.astimezone(timezone.utc)
        self.assertEqual(start, datetime(2026, 9, 22, 8, 9, tzinfo=timezone.utc))

    def test_default_period_follows_open_window(self) -> None:
        self.assertEqual(config.default_period_key(BEFORE_S4), config.LIFETIME_KEY)
        self.assertEqual(config.default_period_key(DURING_S4), config.SEASON4_KEY)
        self.assertEqual(config.default_period_key(AFTER_S4), config.S4_OFFSEASON_KEY)
        self.assertEqual(config.default_period_key(DURING_OFFSEASON), config.S4_OFFSEASON_KEY)
        self.assertEqual(config.default_period_key(AFTER_S5), config.SEASON5_KEY)

    def test_period_choices_include_season5_and_offseason(self) -> None:
        values = dict(config.period_choice_values())
        self.assertEqual(values["season5"], config.SEASON5_KEY)
        self.assertEqual(values["s4 off-season"], config.S4_OFFSEASON_KEY)
        self.assertEqual(values["season4"], config.SEASON4_KEY)
        self.assertEqual(values["lifetime"], config.LIFETIME_KEY)
        names = [name for name, _ in config.period_choice_values()]
        self.assertEqual(names[0], "season5")

    def test_offseason_ranking_floor_is_15_games(self) -> None:
        self.assertEqual(db.min_games_for_ranking(config.S4_OFFSEASON_KEY), 15)
        self.assertEqual(db.min_games_for_ranking(config.SEASON4_KEY), 75)
        self.assertEqual(db.min_games_for_ranking(config.SEASON5_KEY), 75)
        self.assertEqual(db.min_games_for_ranking(config.LIFETIME_KEY), 100)


class SeasonFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = config.DB_PATH
        config.DB_PATH = Path(self._tmpdir.name) / "test.sqlite3"
        self._original_now = db._now
        db._now = lambda: DURING_S4
        db.init_db()

    def tearDown(self) -> None:
        db._now = self._original_now
        config.DB_PATH = self._original_db
        self._tmpdir.cleanup()

    def test_open_season_tracks_delta_from_start_baseline(self) -> None:
        db.track_player_stats("u1", "Player", _raw(games_played=100, kills=50, games_won=40, rounds_played=300))
        db.track_player_stats("u1", "Player", _raw(games_played=120, kills=60, games_won=48, rounds_played=360))

        s4 = db.get_player_raw("u1", config.SEASON4_KEY)
        self.assertEqual(s4["games_played"], 20)
        self.assertEqual(s4["kills"], 10)
        self.assertEqual(db.get_player_raw("u1", config.S4_OFFSEASON_KEY)["games_played"], 0)

    def test_new_games_after_cutoff_go_to_offseason_not_season4(self) -> None:
        db.track_player_stats("u1", "Player", _raw(games_played=100, kills=50, games_won=40, rounds_played=300))
        db.track_player_stats("u1", "Player", _raw(games_played=175, kills=80, games_won=70, rounds_played=500))

        s4_before_freeze = db.get_player_raw("u1", config.SEASON4_KEY)
        self.assertEqual(s4_before_freeze["games_played"], 75)

        db._now = lambda: AFTER_S4
        # Stamp the snapshot after the cutoff so later games are off-season, not a stale S4 gap.
        db.track_player_stats("u1", "Player", _raw(games_played=175, kills=80, games_won=70, rounds_played=500))
        db.freeze_season_end(config.SEASON4_KEY, config.S4_OFFSEASON_KEY)
        db.mark_season_activated(config.S4_OFFSEASON_KEY)

        db.track_player_stats("u1", "Player", _raw(games_played=190, kills=90, games_won=76, rounds_played=540))

        s4 = db.get_player_raw("u1", config.SEASON4_KEY)
        off = db.get_player_raw("u1", config.S4_OFFSEASON_KEY)
        lifetime = db.get_player_raw("u1", config.LIFETIME_KEY)

        self.assertEqual(s4["games_played"], 75)
        self.assertEqual(s4["kills"], 30)
        self.assertEqual(off["games_played"], 15)
        self.assertEqual(off["kills"], 10)
        self.assertEqual(lifetime["games_played"], 190)

    def test_stale_pre_cutoff_snapshot_is_attributed_to_season4(self) -> None:
        db.track_player_stats("u1", "Player", _raw(games_played=100, kills=50, games_won=40, rounds_played=300))
        db._now = lambda: AFTER_S4

        db.track_player_stats("u1", "Player", _raw(games_played=437, kills=200, games_won=180, rounds_played=1200))

        s4 = db.get_player_raw("u1", config.SEASON4_KEY)
        off = db.get_player_raw("u1", config.S4_OFFSEASON_KEY)
        self.assertEqual(s4["games_played"], 337)
        self.assertEqual(off["games_played"], 0)

        db.track_player_stats("u1", "Player", _raw(games_played=447, kills=204, games_won=184, rounds_played=1230))
        self.assertEqual(db.get_player_raw("u1", config.SEASON4_KEY)["games_played"], 337)
        self.assertEqual(db.get_player_raw("u1", config.S4_OFFSEASON_KEY)["games_played"], 10)

    def test_closed_season_start_baselines_are_not_repaired_from_later_games(self) -> None:
        db.track_player_stats("u1", "Player", _raw(games_played=100, kills=50, games_won=40, rounds_played=300))
        db._now = lambda: AFTER_S4
        db.freeze_season_end(config.SEASON4_KEY, config.S4_OFFSEASON_KEY)
        db.track_player_stats("u1", "Player", _raw(games_played=400, kills=200, games_won=160, rounds_played=1200))

        self.assertFalse(db.repair_player_baseline("u1", config.SEASON4_KEY))
        self.assertEqual(db.repair_season_baselines(config.SEASON4_KEY), 0)
        # The S4 *start* baseline stays at 100; the uncounted gap is locked into S4 finals.
        self.assertEqual(db.get_player_raw("u1", config.SEASON4_KEY)["games_played"], 300)
        self.assertEqual(db.get_player_raw("u1", config.S4_OFFSEASON_KEY)["games_played"], 0)

    def test_first_seen_during_offseason_has_no_season4_stats(self) -> None:
        db._now = lambda: AFTER_S4
        db.track_player_stats("u2", "NewPlayer", _raw(games_played=80, kills=20, games_won=30, rounds_played=200))
        db.track_player_stats("u2", "NewPlayer", _raw(games_played=90, kills=24, games_won=34, rounds_played=230))

        self.assertEqual(db.get_player_raw("u2", config.SEASON4_KEY)["games_played"], 0)
        self.assertEqual(db.get_player_raw("u2", config.S4_OFFSEASON_KEY)["games_played"], 10)

    def test_bulk_freeze_locks_every_tracked_season4_player(self) -> None:
        db.track_player_stats("a", "A", _raw(games_played=100, kills=10, games_won=40, rounds_played=200))
        db.track_player_stats("b", "B", _raw(games_played=120, kills=20, games_won=50, rounds_played=240))
        db.track_player_stats("a", "A", _raw(games_played=140, kills=18, games_won=55, rounds_played=280))
        db.track_player_stats("b", "B", _raw(games_played=150, kills=30, games_won=60, rounds_played=300))

        db._now = lambda: AFTER_S4
        db.upsert_player_stats("a", "A", _raw(games_played=140, kills=18, games_won=55, rounds_played=280))
        db.upsert_player_stats("b", "B", _raw(games_played=150, kills=30, games_won=60, rounds_played=300))
        finals, baselines = db.freeze_season_end(config.SEASON4_KEY, config.S4_OFFSEASON_KEY)
        self.assertEqual(finals, 2)
        self.assertEqual(baselines, 2)

        db.track_player_stats("a", "A", _raw(games_played=200, kills=40, games_won=80, rounds_played=400))
        self.assertEqual(db.get_player_raw("a", config.SEASON4_KEY)["games_played"], 40)
        self.assertEqual(db.get_player_raw("b", config.SEASON4_KEY)["games_played"], 30)
        self.assertEqual(db.get_player_raw("a", config.S4_OFFSEASON_KEY)["games_played"], 60)
        self.assertEqual(db.get_player_raw("b", config.S4_OFFSEASON_KEY)["games_played"], 0)

    def test_boot_repair_moves_s4_backlog_out_of_offseason(self) -> None:
        db.track_player_stats("u1", "Player", _raw(games_played=100, kills=50, games_won=40, rounds_played=300))
        db._now = lambda: AFTER_S4
        db.freeze_season_end(config.SEASON4_KEY, config.S4_OFFSEASON_KEY)
        db.upsert_player_stats("u1", "Player", _raw(games_played=437, kills=200, games_won=180, rounds_played=1200))

        self.assertEqual(db.get_player_raw("u1", config.S4_OFFSEASON_KEY)["games_played"], 337)
        self.assertEqual(db.repair_stale_offseason_splits(), 1)
        self.assertEqual(db.get_player_raw("u1", config.SEASON4_KEY)["games_played"], 337)
        self.assertEqual(db.get_player_raw("u1", config.S4_OFFSEASON_KEY)["games_played"], 0)
        self.assertEqual(db.repair_stale_offseason_splits(), 0)

    def test_larppickleman_is_rebaselined_once(self) -> None:
        db.track_player_stats(
            "pickle",
            "LarpPickleMan",
            _raw(games_played=100, kills=50, games_won=40, rounds_played=300),
        )
        db.track_player_stats(
            "pickle",
            "LarpPickleMan",
            _raw(games_played=180, kills=90, games_won=70, rounds_played=500),
        )
        db._now = lambda: AFTER_S4
        db.freeze_season_end(config.SEASON4_KEY, config.S4_OFFSEASON_KEY)
        db.upsert_player_stats(
            "pickle",
            "LarpPickleMan",
            _raw(games_played=517, kills=240, games_won=200, rounds_played=1400),
        )

        # Mid-S4 snapshot (180) would not match the "start==off" heuristic, so the
        # named one-time repair still has to catch this player.
        self.assertEqual(db.get_player_raw("pickle", config.S4_OFFSEASON_KEY)["games_played"], 337)
        self.assertEqual(db.repair_stale_offseason_splits(), 1)
        self.assertEqual(db.get_player_raw("pickle", config.SEASON4_KEY)["games_played"], 417)
        self.assertEqual(db.get_player_raw("pickle", config.S4_OFFSEASON_KEY)["games_played"], 0)

        db.track_player_stats(
            "pickle",
            "LarpPickleMan",
            _raw(games_played=527, kills=244, games_won=204, rounds_played=1430),
        )
        self.assertEqual(db.repair_stale_offseason_splits(), 0)
        self.assertEqual(db.get_player_raw("pickle", config.S4_OFFSEASON_KEY)["games_played"], 10)

    def test_new_games_after_season5_go_to_season5_not_offseason(self) -> None:
        db.track_player_stats("u1", "Player", _raw(games_played=100, kills=50, games_won=40, rounds_played=300))
        db.track_player_stats("u1", "Player", _raw(games_played=175, kills=80, games_won=70, rounds_played=500))

        db._now = lambda: DURING_OFFSEASON
        db.track_player_stats("u1", "Player", _raw(games_played=175, kills=80, games_won=70, rounds_played=500))
        db.freeze_season_end(config.SEASON4_KEY, config.S4_OFFSEASON_KEY)
        db.mark_season_activated(config.S4_OFFSEASON_KEY)
        db.track_player_stats("u1", "Player", _raw(games_played=190, kills=90, games_won=76, rounds_played=540))

        # Stamp the off-season snapshot after the S5 cutoff so later games are S5.
        db._now = lambda: AFTER_S5
        db.track_player_stats("u1", "Player", _raw(games_played=190, kills=90, games_won=76, rounds_played=540))
        db.freeze_season_end(config.S4_OFFSEASON_KEY, config.SEASON5_KEY)
        db.mark_season_activated(config.SEASON5_KEY)

        db.track_player_stats("u1", "Player", _raw(games_played=205, kills=100, games_won=82, rounds_played=580))

        s4 = db.get_player_raw("u1", config.SEASON4_KEY)
        off = db.get_player_raw("u1", config.S4_OFFSEASON_KEY)
        s5 = db.get_player_raw("u1", config.SEASON5_KEY)
        lifetime = db.get_player_raw("u1", config.LIFETIME_KEY)

        self.assertEqual(s4["games_played"], 75)
        self.assertEqual(off["games_played"], 15)
        self.assertEqual(s5["games_played"], 15)
        self.assertEqual(s5["kills"], 10)
        self.assertEqual(lifetime["games_played"], 205)

    def test_first_seen_during_season5_has_no_prior_season_stats(self) -> None:
        db._now = lambda: AFTER_S5
        db.track_player_stats("u3", "S5Player", _raw(games_played=80, kills=20, games_won=30, rounds_played=200))
        db.track_player_stats("u3", "S5Player", _raw(games_played=90, kills=24, games_won=34, rounds_played=230))

        self.assertEqual(db.get_player_raw("u3", config.SEASON4_KEY)["games_played"], 0)
        self.assertEqual(db.get_player_raw("u3", config.S4_OFFSEASON_KEY)["games_played"], 0)
        self.assertEqual(db.get_player_raw("u3", config.SEASON5_KEY)["games_played"], 10)


if __name__ == "__main__":
    unittest.main()
