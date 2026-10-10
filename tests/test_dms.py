"""User DMs to the bot are stored for the owner inbox."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
import db.database as db


class BotDmInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = config.DB_PATH
        config.DB_PATH = Path(self._tmpdir.name) / "test.sqlite3"
        db.init_db()

    def tearDown(self) -> None:
        config.DB_PATH = self._original_db
        self._tmpdir.cleanup()

    def test_save_and_list_newest_first(self) -> None:
        first = db.save_bot_dm("1", "Alice", "alice", "want a pink name")
        second = db.save_bot_dm("2", "Bob", "bob", "vip color please", "ref.png")
        self.assertGreater(second, first)

        rows = db.list_bot_dms()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["username"], "bob")
        self.assertEqual(rows[0]["attachments"], "ref.png")
        self.assertEqual(rows[1]["content"], "want a pink name")
        self.assertEqual(rows[1]["discord_id"], "1")

    def test_empty_inbox(self) -> None:
        self.assertEqual(db.list_bot_dms(), [])


if __name__ == "__main__":
    unittest.main()
