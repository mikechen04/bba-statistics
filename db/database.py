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

CREATE TABLE IF NOT EXISTS season_stat_baselines (
    season_key TEXT NOT NULL,
    uuid TEXT NOT NULL,
    username TEXT NOT NULL,
    {", ".join(f"{k} INTEGER NOT NULL DEFAULT 0" for k in RAW_KEYS)},
    captured_at TEXT NOT NULL,
    PRIMARY KEY (season_key, uuid)
);

CREATE TABLE IF NOT EXISTS bot_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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
        baseline_cols = {row[1] for row in conn.execute("PRAGMA table_info(season_stat_baselines)")}
        for key in RAW_KEYS:
            if key not in baseline_cols:
                conn.execute(f"ALTER TABLE season_stat_baselines ADD COLUMN {key} INTEGER NOT NULL DEFAULT 0")


def _raw_values(raw: dict[str, int]) -> list[int]:
    return [int(raw.get(k) or 0) for k in RAW_KEYS]


def _row_to_raw(row: sqlite3.Row | dict | None) -> dict[str, int]:
    if row is None:
        return {k: 0 for k in RAW_KEYS}
    return {k: int((row[k] if isinstance(row, sqlite3.Row) else row.get(k)) or 0) for k in RAW_KEYS}


def _current_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_season_started(season_key: str) -> bool:
    return season_key == config.SEASON4_KEY and datetime.now(timezone.utc) >= config.SEASON4_START_AT.astimezone(timezone.utc)


def _season_meta_key(season_key: str) -> str:
    return f"{season_key}_activated_at"


def get_meta(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM bot_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO bot_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def season_needs_activation(season_key: str) -> bool:
    return is_season_started(season_key) and get_meta(_season_meta_key(season_key)) is None


def upsert_player_stats(uuid: str, username: str, raw: dict[str, int]) -> None:
    """Insert or refresh a player's tracked snapshot. Called on every lookup."""
    columns = ["uuid", "username", *RAW_KEYS, "updated_at"]
    values = [uuid, username, *_raw_values(raw), _current_time()]
    placeholders = ", ".join("?" for _ in columns)
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "uuid")
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO bba_stats ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(uuid) DO UPDATE SET {update_clause}",
            values,
        )


def ensure_season_baseline(uuid: str, username: str, raw: dict[str, int], season_key: str = config.SEASON4_KEY) -> None:
    """Freeze this player's lifetime totals as their season-start baseline once."""
    if not is_season_started(season_key):
        return
    columns = ["season_key", "uuid", "username", *RAW_KEYS, "captured_at"]
    values = [season_key, uuid, username, *_raw_values(raw), _current_time()]
    placeholders = ", ".join("?" for _ in columns)
    with _connect() as conn:
        conn.execute(
            f"INSERT OR IGNORE INTO season_stat_baselines ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )


def capture_season_baselines_for_all(season_key: str = config.SEASON4_KEY) -> int:
    """Freeze all currently tracked lifetime rows as baselines for a season."""
    with _connect() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM season_stat_baselines WHERE season_key = ?",
            (season_key,),
        ).fetchone()[0]
        conn.execute(
            f"""
            INSERT OR IGNORE INTO season_stat_baselines (
                season_key, uuid, username, {", ".join(RAW_KEYS)}, captured_at
            )
            SELECT ?, uuid, username, {", ".join(RAW_KEYS)}, ?
            FROM bba_stats
            """,
            (season_key, _current_time()),
        )
        after = conn.execute(
            "SELECT COUNT(*) FROM season_stat_baselines WHERE season_key = ?",
            (season_key,),
        ).fetchone()[0]
    return int(after - before)


def mark_season_activated(season_key: str = config.SEASON4_KEY) -> None:
    set_meta(_season_meta_key(season_key), _current_time())


def _baseline_map(season_key: str) -> dict[str, dict[str, int]]:
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT uuid, {', '.join(RAW_KEYS)} FROM season_stat_baselines WHERE season_key = ?",
            (season_key,),
        ).fetchall()
    return {row["uuid"]: _row_to_raw(row) for row in rows}


def _season_raw_from_rows(current_row: dict, baseline_raw: dict[str, int]) -> dict:
    season_row = {"uuid": current_row["uuid"], "username": current_row["username"]}
    for key in RAW_KEYS:
        season_row[key] = max(int(current_row.get(key) or 0) - int(baseline_raw.get(key) or 0), 0)
    return season_row


def all_raw_rows(period: str = "lifetime") -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(f"SELECT uuid, username, {', '.join(RAW_KEYS)} FROM bba_stats").fetchall()
    current_rows = [dict(row) for row in rows]
    if period == "lifetime":
        return current_rows
    if not is_season_started(period):
        return []
    baselines = _baseline_map(period)
    return [
        _season_raw_from_rows(row, baselines[row["uuid"]])
        for row in current_rows
        if row["uuid"] in baselines
    ]


def get_player_raw(uuid: str, period: str = "lifetime") -> dict[str, int]:
    with _connect() as conn:
        row = conn.execute(
            f"SELECT uuid, username, {', '.join(RAW_KEYS)} FROM bba_stats WHERE uuid = ?",
            (uuid,),
        ).fetchone()
    if row is None:
        return {k: 0 for k in RAW_KEYS}
    current = dict(row)
    if period == "lifetime":
        return _row_to_raw(current)
    if not is_season_started(period):
        return {k: 0 for k in RAW_KEYS}
    baselines = _baseline_map(period)
    baseline = baselines.get(uuid)
    if baseline is None:
        return {k: 0 for k in RAW_KEYS}
    return _season_raw_from_rows(current, baseline)


def tracked_player_count(period: str = "lifetime") -> int:
    if period == "lifetime":
        with _connect() as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM bba_stats").fetchone()
        return count
    return len(all_raw_rows(period))


def qualified_player_count(period: str = "lifetime") -> int:
    """Count of tracked players that meet the minimum-games bar to be ranked."""
    rows = all_raw_rows(period)
    return sum(1 for row in rows if (row.get("games_played") or 0) >= MIN_GAMES_FOR_RANKING)


def compute_percentiles(uuid: str, period: str = "lifetime") -> dict[str, dict]:
    """For each metric, return {rank, total, percentile} for the given player,
    computed against every *qualified* (100+ games) player currently tracked in
    the local database for the requested period.
    """
    rows = [r for r in all_raw_rows(period) if (r.get("games_played") or 0) >= MIN_GAMES_FOR_RANKING]
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


def compute_leaderboard(metric_key: str, period: str = "lifetime") -> list[dict]:
    """Ranks every qualified (100+ games) tracked player for a single metric."""
    metric = METRICS.get(metric_key)
    if metric is None:
        return []

    rows = [r for r in all_raw_rows(period) if (r.get("games_played") or 0) >= MIN_GAMES_FOR_RANKING]
    scored = [(row["uuid"], row["username"], compute_all(row)[metric_key]) for row in rows]
    scored.sort(key=lambda t: t[2], reverse=(metric.direction != "asc"))
    return [
        {"rank": i + 1, "uuid": uuid, "username": username, "value": value}
        for i, (uuid, username, value) in enumerate(scored)
    ]


def tracked_player_count_lifetime() -> int:
    with _connect() as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM bba_stats").fetchone()
    return count


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
