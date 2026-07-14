"""SQLite persistence: tracked player stat snapshots, and Discord-account links.

Percentiles shown by the bot are computed relative to the pool of players this
bot has looked up before (see stats/derive.py + compute_percentiles below), not
a true server-wide percentile -- the public MCC Island API doesn't expose a
global leaderboard or player count for most Battle Box Arena stats. This is
surfaced to users in the rendered card footer.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import config
from stats.derive import METRICS, RAW_KEYS, compute_all

_lock = threading.Lock()

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS bba_stats (
    uuid TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    {", ".join(f"{k} INTEGER NOT NULL DEFAULT 0" for k in RAW_KEYS)},
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS linked_accounts (
    discord_id TEXT PRIMARY KEY,
    uuid TEXT NOT NULL,
    username TEXT NOT NULL,
    linked_at TEXT NOT NULL
);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with _lock:
            yield conn
            conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def upsert_player_stats(uuid: str, username: str, raw: dict[str, int]) -> None:
    """Insert or refresh a player's tracked snapshot. Called on every lookup."""
    columns = ["uuid", "username", *RAW_KEYS, "updated_at"]
    values = [uuid, username, *[raw.get(k) or 0 for k in RAW_KEYS], datetime.now(timezone.utc).isoformat()]
    placeholders = ", ".join("?" for _ in columns)
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "uuid")
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO bba_stats ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(uuid) DO UPDATE SET {update_clause}",
            values,
        )


def all_raw_rows() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(f"SELECT uuid, username, {', '.join(RAW_KEYS)} FROM bba_stats").fetchall()
    return [dict(row) for row in rows]


def tracked_player_count() -> int:
    with _connect() as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM bba_stats").fetchone()
    return count


def compute_percentiles(uuid: str) -> dict[str, dict]:
    """For each metric, return {rank, total, percentile} for the given player,
    computed against every player currently tracked in the local database.
    """
    rows = all_raw_rows()
    total = len(rows)
    if total == 0:
        return {}

    computed_by_uuid = {row["uuid"]: compute_all(row) for row in rows}
    if uuid not in computed_by_uuid:
        return {}

    results: dict[str, dict] = {}
    for key, metric in METRICS.items():
        values = [computed_by_uuid[row["uuid"]][key] for row in rows]
        my_value = computed_by_uuid[uuid][key]
        if metric.direction == "asc":
            better_count = sum(1 for v in values if v < my_value)
        else:
            better_count = sum(1 for v in values if v > my_value)
        rank = better_count + 1
        percentile = round((1 - (rank - 1) / total) * 100, 1) if total else 0.0
        results[key] = {"rank": rank, "total": total, "percentile": percentile}
    return results


def link_account(discord_id: str, uuid: str, username: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO linked_accounts (discord_id, uuid, username, linked_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET uuid = excluded.uuid, username = excluded.username, "
            "linked_at = excluded.linked_at",
            (discord_id, uuid, username, datetime.now(timezone.utc).isoformat()),
        )


def unlink_account(discord_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM linked_accounts WHERE discord_id = ?", (discord_id,))
    return cur.rowcount > 0


def get_linked_account(discord_id: str) -> tuple[str, str] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT uuid, username FROM linked_accounts WHERE discord_id = ?", (discord_id,)
        ).fetchone()
    return (row["uuid"], row["username"]) if row else None
