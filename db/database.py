"""SQLite persistence: tracked player stat snapshots, and Discord-account links.

Percentiles shown by the bot are computed relative to the pool of players
tracked in this table, not a true server-wide percentile -- the MCC Island API
doesn't expose a full player list or a leaderboard for most Battle Box Arena
stats, so there's no way to enumerate "every player on MCC Island". This is
surfaced to users in the rendered card footer.

The pool is grown from three sources so it isn't limited to whoever gets
searched directly:
  1. Every `/bbastats` lookup upserts that player (cogs/stats.py).
  2. Every `/bbaparty` lookup opportunistically upserts the whole party, not
     just the searched player (cogs/party.py).
  3. A periodic background job crawls the handful of BBA stats that do have a
     public API leaderboard (wins, round wins, kills) to seed real
     high-activity players in bulk (see mcc_api.client.get_leaderboard and
     bot.py's `seed_leaderboards` task).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import config
from stats.derive import METRICS, RAW_KEYS, compute_all

_lock = threading.Lock()

# Players with fewer games than this aren't stable enough samples to rank against,
# so they're excluded both from the ranking pool (they don't count as a comparison
# point for others) and from receiving a rank/percentile themselves. Their raw
# stats are still shown on the card either way -- this only affects rank badges.
MIN_GAMES_FOR_RANKING = 100

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
        # Forward-compatible migration: if a new raw stat key is added later
        # (e.g. playtime), add its column instead of requiring a DB wipe.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(bba_stats)")}
        for key in RAW_KEYS:
            if key not in existing_cols:
                conn.execute(f"ALTER TABLE bba_stats ADD COLUMN {key} INTEGER NOT NULL DEFAULT 0")


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


def qualified_player_count() -> int:
    """Count of tracked players that meet the minimum-games bar to be ranked."""
    with _connect() as conn:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM bba_stats WHERE games_played >= ?", (MIN_GAMES_FOR_RANKING,)
        ).fetchone()
    return count


def compute_percentiles(uuid: str) -> dict[str, dict]:
    """For each metric, return {rank, total, percentile} for the given player,
    computed against every *qualified* (100+ games) player currently tracked in
    the local database. Players below that bar get no rank/percentile at all,
    and don't count towards other players' totals either.
    """
    rows = [r for r in all_raw_rows() if (r.get("games_played") or 0) >= MIN_GAMES_FOR_RANKING]
    total = len(rows)
    if total == 0:
        return {}

    computed_by_uuid = {row["uuid"]: compute_all(row) for row in rows}
    if uuid not in computed_by_uuid:
        return {}

    results: dict[str, dict] = {}
    for key, metric in METRICS.items():
        if not metric.rankable:
            continue
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
