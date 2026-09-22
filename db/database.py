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

Season stats are lifetime totals minus a frozen season-start baseline. Baselines
that were captured from empty/incomplete rows are repaired on startup so season
boards don't accidentally show lifetime values.

When a season ends, each player's lifetime totals at the cutoff are copied into
`season_stat_finals` (immutable) and into the next period's start baseline.
Closed-season stats are always `finals - start`, so later games cannot change
them. The next period (e.g. Season 5 after S4 Off-Season) is `current - that baseline`.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import config
from stats.derive import METRICS, RAW_KEYS, compute_all

_lock = threading.Lock()

# Players below these bars aren't stable enough samples to rank against.
MIN_GAMES_FOR_RANKING_LIFETIME = 100
MIN_GAMES_FOR_RANKING_SEASON = 75

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

CREATE TABLE IF NOT EXISTS season_stat_finals (
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


def min_games_for_ranking(period: str = "lifetime") -> int:
    if period == "lifetime" or period == config.LIFETIME_KEY:
        return MIN_GAMES_FOR_RANKING_LIFETIME
    configured = config.get_period(period)
    if configured is not None:
        return configured.min_games
    return MIN_GAMES_FOR_RANKING_SEASON


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
        finals_cols = {row[1] for row in conn.execute("PRAGMA table_info(season_stat_finals)")}
        for key in RAW_KEYS:
            if key not in finals_cols:
                conn.execute(f"ALTER TABLE season_stat_finals ADD COLUMN {key} INTEGER NOT NULL DEFAULT 0")

    # Safe to run every boot: fixes empty/incomplete start baselines in place.
    # Never repair a closed season — current lifetime already includes later games.
    for period in config.STAT_PERIODS.values():
        if is_season_open(period.key):
            repair_season_baselines(period.key)
    repair_stale_offseason_splits()


def _raw_values(raw: dict[str, int]) -> list[int]:
    return [int(raw.get(k) or 0) for k in RAW_KEYS]


def _row_to_raw(row: sqlite3.Row | dict | None) -> dict[str, int]:
    if row is None:
        return {k: 0 for k in RAW_KEYS}
    return {k: int((row[k] if isinstance(row, sqlite3.Row) else row.get(k)) or 0) for k in RAW_KEYS}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_predates_period_end(row: dict, period: config.StatPeriod) -> bool:
    """True when the stored lifetime row was last updated before this period ended."""
    if period.end_at is None:
        return False
    updated = _parse_iso(row.get("updated_at") if isinstance(row, dict) else None)
    end = period.end_at.astimezone(timezone.utc)
    if updated is None:
        return True
    return updated < end


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _current_time() -> str:
    return _now().isoformat()


def is_season_started(season_key: str) -> bool:
    period = config.get_period(season_key)
    if period is None:
        return False
    return _now() >= period.start_at.astimezone(timezone.utc)


def is_season_ended(season_key: str) -> bool:
    period = config.get_period(season_key)
    if period is None or period.end_at is None:
        return False
    return _now() >= period.end_at.astimezone(timezone.utc)


def is_season_open(season_key: str) -> bool:
    return is_season_started(season_key) and not is_season_ended(season_key)


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


def delete_meta(key: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM bot_meta WHERE key = ?", (key,))
    return cur.rowcount > 0


_BBASTATS_NAME_COLOR_PREFIX = "bbastats_name_color:"


def set_bbastats_name_color(username: str, color: tuple[int, int, int]) -> None:
    key = f"{_BBASTATS_NAME_COLOR_PREFIX}{username.lower()}"
    set_meta(key, f"{color[0]},{color[1]},{color[2]}")


def clear_bbastats_name_color(username: str) -> bool:
    return delete_meta(f"{_BBASTATS_NAME_COLOR_PREFIX}{username.lower()}")


def get_bbastats_name_color(username: str) -> tuple[int, int, int] | None:
    raw = get_meta(f"{_BBASTATS_NAME_COLOR_PREFIX}{username.lower()}")
    if not raw:
        return None
    parts = raw.split(",")
    if len(parts) != 3:
        return None
    try:
        rgb = tuple(int(p) for p in parts)
    except ValueError:
        return None
    if any(c < 0 or c > 255 for c in rgb):
        return None
    return rgb


def season_needs_activation(season_key: str) -> bool:
    return is_season_started(season_key) and get_meta(_season_meta_key(season_key)) is None


def _merge_raw(existing: dict | None, raw: dict) -> dict[str, int] | None:
    """Merge an API payload into an existing row without wiping good data.

    Returns None when the payload is empty/unusable and should be ignored.
    Lifetime counters are treated as monotonic: a glitchy/partial payload must
    not roll a tracked total backwards (that can make an older season delta
    look higher than the newer lifetime total).
    """
    provided = {k: int(raw[k]) for k in RAW_KEYS if k in raw and raw[k] is not None}
    if not provided:
        return None

    if existing:
        existing_games = int(existing.get("games_played") or 0)
        # A fully-zero payload must not erase a populated tracked row (seen when
        # leaderboard seeds return players whose nested statistics block is empty).
        if existing_games > 0 and len(provided) == len(RAW_KEYS) and all(v == 0 for v in provided.values()):
            return None
        merged: dict[str, int] = {}
        for key in RAW_KEYS:
            old_val = int(existing.get(key) or 0)
            if key in provided:
                merged[key] = max(provided[key], old_val)
            else:
                merged[key] = old_val
        return merged

    return {k: provided.get(k, 0) for k in RAW_KEYS}


def upsert_player_stats(uuid: str, username: str, raw: dict[str, int]) -> None:
    """Insert or refresh a player's tracked snapshot. Called on every lookup."""
    with _connect() as conn:
        existing_row = conn.execute("SELECT * FROM bba_stats WHERE uuid = ?", (uuid,)).fetchone()
        existing = dict(existing_row) if existing_row else None
        merged = _merge_raw(existing, raw)
        if merged is None:
            if existing is not None and username and username != existing.get("username"):
                conn.execute(
                    "UPDATE bba_stats SET username = ?, updated_at = ? WHERE uuid = ?",
                    (username, _current_time(), uuid),
                )
            return

        columns = ["uuid", "username", *RAW_KEYS, "updated_at"]
        values = [uuid, username, *_raw_values(merged), _current_time()]
        placeholders = ", ".join("?" for _ in columns)
        update_clause = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "uuid")
        conn.execute(
            f"INSERT INTO bba_stats ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(uuid) DO UPDATE SET {update_clause}",
            values,
        )


def ensure_season_baseline(uuid: str, username: str, raw: dict[str, int] | None = None, season_key: str = config.SEASON4_KEY) -> None:
    """Freeze this player's lifetime totals as their season-start baseline once."""
    if not is_season_open(season_key):
        return

    with _connect() as conn:
        row = conn.execute("SELECT * FROM bba_stats WHERE uuid = ?", (uuid,)).fetchone()
        if row is not None:
            baseline_raw = _row_to_raw(row)
            baseline_username = row["username"] or username
        elif raw is not None:
            merged = _merge_raw(None, raw)
            if merged is None:
                return
            baseline_raw = merged
            baseline_username = username
        else:
            return

        # Never freeze an all-zero baseline when we don't have a real snapshot yet.
        if all(v == 0 for v in baseline_raw.values()):
            return

        _insert_baseline_ignore(conn, season_key, uuid, baseline_username, baseline_raw)


def _insert_baseline_ignore(
    conn: sqlite3.Connection, season_key: str, uuid: str, username: str, raw: dict[str, int]
) -> None:
    columns = ["season_key", "uuid", "username", *RAW_KEYS, "captured_at"]
    values = [season_key, uuid, username, *_raw_values(raw), _current_time()]
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT OR IGNORE INTO season_stat_baselines ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )


def _insert_final_ignore(
    conn: sqlite3.Connection, season_key: str, uuid: str, username: str, raw: dict[str, int]
) -> None:
    """Write an immutable end-of-season snapshot. Never overwrites an existing final."""
    columns = ["season_key", "uuid", "username", *RAW_KEYS, "captured_at"]
    values = [season_key, uuid, username, *_raw_values(raw), _current_time()]
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT OR IGNORE INTO season_stat_finals ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )


def freeze_player_before_update(uuid: str) -> None:
    """If a season has ended, freeze this player's last known totals before a new upsert.

    Skips snapshots that predate the cutoff. Those rows still include the whole
    uncounted S4 gap; freezing them would dump that gap into off-season.
    """
    existing = None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM bba_stats WHERE uuid = ?", (uuid,)).fetchone()
        if row is not None:
            existing = dict(row)

    if existing is None:
        return

    baseline_raw = _row_to_raw(existing)
    if all(v == 0 for v in baseline_raw.values()):
        return

    username = existing.get("username") or ""
    with _connect() as conn:
        for period in config.STAT_PERIODS.values():
            if not is_season_ended(period.key):
                continue
            nxt = config.next_period(period.key)
            if nxt is None:
                continue
            if _snapshot_predates_period_end(existing, period):
                continue
            has_start = conn.execute(
                "SELECT 1 FROM season_stat_baselines WHERE season_key = ? AND uuid = ?",
                (period.key, uuid),
            ).fetchone()
            if has_start:
                _insert_final_ignore(conn, period.key, uuid, username, baseline_raw)
            _insert_baseline_ignore(conn, nxt.key, uuid, username, baseline_raw)


def _stale_closed_periods(uuid: str) -> list[config.StatPeriod]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM bba_stats WHERE uuid = ?", (uuid,)).fetchone()
    if row is None:
        return []
    existing = dict(row)
    stale: list[config.StatPeriod] = []
    for period in config.STAT_PERIODS.values():
        if not is_season_ended(period.key):
            continue
        if config.next_period(period.key) is None:
            continue
        if _snapshot_predates_period_end(existing, period):
            stale.append(period)
    return stale


def _rebaseline_closed_seasons_to_current(uuid: str, periods: list[config.StatPeriod] | None = None) -> bool:
    """Move an uncounted closed-season gap out of the next period by restarting it at now."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM bba_stats WHERE uuid = ?", (uuid,)).fetchone()
        if row is None:
            return False
        current = _row_to_raw(row)
        if all(v == 0 for v in current.values()):
            return False
        username = row["username"] or ""
        targets = periods if periods is not None else list(config.STAT_PERIODS.values())
        wrote = False
        for period in targets:
            if not is_season_ended(period.key):
                continue
            nxt = config.next_period(period.key)
            if nxt is None:
                continue
            has_start = conn.execute(
                "SELECT 1 FROM season_stat_baselines WHERE season_key = ? AND uuid = ?",
                (period.key, uuid),
            ).fetchone()
            if has_start:
                _write_final(conn, period.key, uuid, username, current)
            _write_baseline(conn, nxt.key, uuid, username, current)
            wrote = True
    return wrote


def track_player_stats(uuid: str, username: str, raw: dict[str, int], season_key: str | None = None) -> None:
    """Upsert lifetime stats and maintain baselines for every open season.

    `season_key` is ignored; kept so older call sites that passed Season 4 still work.
    """
    del season_key
    stale_periods = _stale_closed_periods(uuid)
    if not stale_periods:
        freeze_player_before_update(uuid)
    upsert_player_stats(uuid, username, raw)
    if stale_periods:
        _rebaseline_closed_seasons_to_current(uuid, stale_periods)
    for period in config.STAT_PERIODS.values():
        if not is_season_open(period.key):
            continue
        ensure_season_baseline(uuid, username, raw, season_key=period.key)
        repair_player_baseline(uuid, period.key)


def capture_season_baselines_for_all(season_key: str = config.SEASON4_KEY) -> int:
    """Freeze all currently tracked lifetime rows as baselines for a season."""
    with _connect() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM season_stat_baselines WHERE season_key = ?",
            (season_key,),
        ).fetchone()[0]
        # Skip empty rows so we don't lock in all-zero baselines that later become
        # full lifetime values and leak onto season leaderboards.
        games_filter = " AND games_played > 0" if "games_played" in RAW_KEYS else ""
        conn.execute(
            f"""
            INSERT OR IGNORE INTO season_stat_baselines (
                season_key, uuid, username, {", ".join(RAW_KEYS)}, captured_at
            )
            SELECT ?, uuid, username, {", ".join(RAW_KEYS)}, ?
            FROM bba_stats
            WHERE 1=1{games_filter}
            """,
            (season_key, _current_time()),
        )
        after = conn.execute(
            "SELECT COUNT(*) FROM season_stat_baselines WHERE season_key = ?",
            (season_key,),
        ).fetchone()[0]
    repaired = repair_season_baselines(season_key)
    return int(after - before) + repaired


def mark_season_activated(season_key: str = config.SEASON4_KEY) -> None:
    set_meta(_season_meta_key(season_key), _current_time())


def capture_season_finals_for_all(season_key: str) -> int:
    """Freeze current lifetime totals as an immutable end snapshot for a closed season."""
    with _connect() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM season_stat_finals WHERE season_key = ?",
            (season_key,),
        ).fetchone()[0]
        games_filter = " AND c.games_played > 0" if "games_played" in RAW_KEYS else ""
        conn.execute(
            f"""
            INSERT OR IGNORE INTO season_stat_finals (
                season_key, uuid, username, {", ".join(RAW_KEYS)}, captured_at
            )
            SELECT ?, c.uuid, c.username, {", ".join(f"c.{k}" for k in RAW_KEYS)}, ?
            FROM bba_stats c
            INNER JOIN season_stat_baselines b
                ON b.uuid = c.uuid AND b.season_key = ?
            WHERE 1=1{games_filter}
            """,
            (season_key, _current_time(), season_key),
        )
        after = conn.execute(
            "SELECT COUNT(*) FROM season_stat_finals WHERE season_key = ?",
            (season_key,),
        ).fetchone()[0]
    return int(after - before)


def freeze_season_end(closed_key: str, next_key: str) -> tuple[int, int]:
    """Lock a closed season's stats and open the next period from the same snapshot."""
    finals = capture_season_finals_for_all(closed_key)
    baselines = capture_season_baselines_for_all(next_key)
    return finals, baselines


def _write_baseline(conn: sqlite3.Connection, season_key: str, uuid: str, username: str, raw: dict[str, int]) -> None:
    columns = ["season_key", "uuid", "username", *RAW_KEYS, "captured_at"]
    values = [season_key, uuid, username, *_raw_values(raw), _current_time()]
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in {"season_key", "uuid"})
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO season_stat_baselines ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(season_key, uuid) DO UPDATE SET {update_clause}",
        values,
    )


def _write_final(conn: sqlite3.Connection, season_key: str, uuid: str, username: str, raw: dict[str, int]) -> None:
    columns = ["season_key", "uuid", "username", *RAW_KEYS, "captured_at"]
    values = [season_key, uuid, username, *_raw_values(raw), _current_time()]
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in {"season_key", "uuid"})
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO season_stat_finals ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(season_key, uuid) DO UPDATE SET {update_clause}",
        values,
    )


_STALE_OFFSEASON_USERNAMES = ("larppickleman",)


def _find_uuid_by_username(username: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT uuid FROM bba_stats WHERE lower(username) = lower(?)",
            (username,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT uuid FROM season_stat_baselines WHERE lower(username) = lower(?) LIMIT 1",
                (username,),
            ).fetchone()
    return row["uuid"] if row else None


def repair_stale_offseason_splits() -> int:
    """Move closed-season backlog out of off-season when the freeze used a stale start snapshot.

    If a player was last cached at Season 4 start (or never updated during S4), the first
    off-season lookup used that old row as the off-season baseline and the entire S4
    delta showed up as off-season games.
    """
    closed = [p for p in config.STAT_PERIODS.values() if is_season_ended(p.key) and config.next_period(p.key) is not None]
    if not closed:
        return 0

    fixed = 0
    with _connect() as conn:
        for period in closed:
            nxt = config.next_period(period.key)
            if nxt is None:
                continue
            rows = conn.execute(
                f"""
                SELECT c.uuid AS uuid, c.username AS username,
                       {", ".join(f"c.{k} AS current_{k}" for k in RAW_KEYS)},
                       {", ".join(f"s.{k} AS start_{k}" for k in RAW_KEYS)},
                       {", ".join(f"o.{k} AS off_{k}" for k in RAW_KEYS)}
                FROM bba_stats c
                JOIN season_stat_baselines s
                    ON s.uuid = c.uuid AND s.season_key = ?
                JOIN season_stat_baselines o
                    ON o.uuid = c.uuid AND o.season_key = ?
                """,
                (period.key, nxt.key),
            ).fetchall()

            for row in rows:
                start_games = int(row["start_games_played"] or 0)
                off_games = int(row["off_games_played"] or 0)
                current_games = int(row["current_games_played"] or 0)
                if not (off_games <= start_games < current_games):
                    continue
                current = {k: int(row[f"current_{k}"] or 0) for k in RAW_KEYS}
                _write_final(conn, period.key, row["uuid"], row["username"], current)
                _write_baseline(conn, nxt.key, row["uuid"], row["username"], current)
                fixed += 1

    for username in _STALE_OFFSEASON_USERNAMES:
        meta_key = f"offseason_rebaselined:{username.lower()}"
        if get_meta(meta_key):
            continue
        uuid = _find_uuid_by_username(username)
        if uuid is None:
            continue
        if _rebaseline_closed_seasons_to_current(uuid):
            set_meta(meta_key, _current_time())
            fixed += 1
    return fixed


def repair_player_baseline(uuid: str, season_key: str = config.SEASON4_KEY) -> bool:
    """Repair one player's baseline if it was captured empty/incomplete."""
    if is_season_ended(season_key):
        return False
    with _connect() as conn:
        current_row = conn.execute("SELECT * FROM bba_stats WHERE uuid = ?", (uuid,)).fetchone()
        baseline_row = conn.execute(
            "SELECT * FROM season_stat_baselines WHERE season_key = ? AND uuid = ?",
            (season_key, uuid),
        ).fetchone()
        if current_row is None or baseline_row is None:
            return False

        current = _row_to_raw(current_row)
        baseline = _row_to_raw(baseline_row)
        repaired = _repaired_baseline(baseline, current)
        if repaired == baseline:
            return False

        _write_baseline(conn, season_key, uuid, current_row["username"], repaired)
        return True


def _repaired_baseline(baseline: dict[str, int], current: dict[str, int]) -> dict[str, int]:
    """Return a corrected baseline for incomplete season-start snapshots."""
    repaired = dict(baseline)
    baseline_games = int(baseline.get("games_played") or 0)
    current_games = int(current.get("games_played") or 0)

    # Empty baseline against a real lifetime row → lifetime was leaking into season.
    # Re-freeze at "now" so season stats start clean from this point forward.
    if baseline_games <= 0 and current_games > 0:
        return dict(current)

    if baseline_games <= 0 or current_games <= 0:
        return repaired

    # Columns that were 0 at capture but are populated now were almost certainly
    # missing from the snapshot (e.g. score). Attribute the pre-season share by
    # games played so season rates aren't inflated to near-lifetime totals.
    for key in RAW_KEYS:
        if key == "games_played":
            continue
        if int(baseline.get(key) or 0) == 0 and int(current.get(key) or 0) > 0:
            repaired[key] = int(round(current[key] * baseline_games / current_games))

    return repaired


def repair_season_baselines(season_key: str = config.SEASON4_KEY) -> int:
    """Repair all incomplete baselines for a season. Returns number repaired."""
    if is_season_ended(season_key):
        return 0
    fixed = 0
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT b.uuid AS uuid, b.username AS username,
                   {", ".join(f"b.{k} AS baseline_{k}" for k in RAW_KEYS)},
                   {", ".join(f"c.{k} AS current_{k}" for k in RAW_KEYS)}
            FROM season_stat_baselines b
            JOIN bba_stats c ON c.uuid = b.uuid
            WHERE b.season_key = ?
            """,
            (season_key,),
        ).fetchall()

        for row in rows:
            baseline = {k: int(row[f"baseline_{k}"] or 0) for k in RAW_KEYS}
            current = {k: int(row[f"current_{k}"] or 0) for k in RAW_KEYS}
            repaired = _repaired_baseline(baseline, current)
            if repaired == baseline:
                continue
            _write_baseline(conn, season_key, row["uuid"], row["username"], repaired)
            fixed += 1
    return fixed


def _finals_map(season_key: str) -> dict[str, dict]:
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT uuid, username, {', '.join(RAW_KEYS)} FROM season_stat_finals WHERE season_key = ?",
            (season_key,),
        ).fetchall()
    return {row["uuid"]: dict(row) for row in rows}


def _current_rows_for_period(period: str, current_rows: list[dict]) -> list[dict]:
    """Lifetime-shaped rows to subtract start baselines from for this period.

    Open periods use live tracked totals. Closed periods use the immutable
    end-of-season finals so later games cannot change the board.
    """
    if not is_season_ended(period):
        return current_rows

    finals = _finals_map(period)
    out: list[dict] = []
    for row in current_rows:
        final = finals.get(row["uuid"])
        if final is not None:
            out.append(final)
        else:
            # Not frozen yet — last tracked lifetime is the best freeze point.
            out.append(row)
    return out


def _sanitize_season_raw(season_row: dict) -> dict:
    """Clamp impossible season deltas caused by baseline/API drift."""
    games = max(int(season_row.get("games_played") or 0), 0)
    rounds = max(int(season_row.get("rounds_played") or 0), 0)
    kills = max(int(season_row.get("kills") or 0), 0)

    season_row["games_played"] = games
    season_row["rounds_played"] = rounds
    season_row["kills"] = kills

    season_row["games_won"] = min(max(int(season_row.get("games_won") or 0), 0), games)
    season_row["top1"] = min(max(int(season_row.get("top1") or 0), 0), games)
    season_row["top3"] = min(max(int(season_row.get("top3") or 0), 0), games)
    season_row["top3"] = max(int(season_row["top3"]), int(season_row["top1"]))

    season_row["rounds_won"] = min(max(int(season_row.get("rounds_won") or 0), 0), rounds)
    season_row["deaths"] = max(int(season_row.get("deaths") or 0), 0)
    season_row["assists"] = max(int(season_row.get("assists") or 0), 0)
    season_row["aces"] = max(int(season_row.get("aces") or 0), 0)
    season_row["score"] = max(int(season_row.get("score") or 0), 0)
    season_row["playtime_ticks"] = max(int(season_row.get("playtime_ticks") or 0), 0)

    melee = max(int(season_row.get("melee_kills") or 0), 0)
    ranged = max(int(season_row.get("ranged_kills") or 0), 0)
    if kills > 0 and melee + ranged > kills:
        scale = kills / (melee + ranged)
        melee = int(round(melee * scale))
        ranged = max(kills - melee, 0)
    season_row["melee_kills"] = min(melee, kills)
    season_row["ranged_kills"] = min(ranged, kills)
    return season_row


def _season_raw_from_rows(current_row: dict, baseline_raw: dict[str, int]) -> dict:
    season_row = {"uuid": current_row["uuid"], "username": current_row["username"]}
    for key in RAW_KEYS:
        current_val = max(int(current_row.get(key) or 0), 0)
        baseline_val = max(int(baseline_raw.get(key) or 0), 0)
        # Season can never exceed the current lifetime total for the same key.
        season_row[key] = min(max(current_val - baseline_val, 0), current_val)
    return _sanitize_season_raw(season_row)


def _baseline_map(season_key: str) -> dict[str, dict[str, int]]:
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT uuid, {', '.join(RAW_KEYS)} FROM season_stat_baselines WHERE season_key = ?",
            (season_key,),
        ).fetchall()
    return {row["uuid"]: _row_to_raw(row) for row in rows}


def all_raw_rows(period: str = "lifetime") -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(f"SELECT uuid, username, {', '.join(RAW_KEYS)} FROM bba_stats").fetchall()
    current_rows = [dict(row) for row in rows]
    if period == "lifetime" or period == config.LIFETIME_KEY:
        return current_rows
    if not is_season_started(period):
        return []
    baselines = _baseline_map(period)
    period_rows = _current_rows_for_period(period, current_rows)
    return [
        _season_raw_from_rows(row, baselines[row["uuid"]])
        for row in period_rows
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
    if period == "lifetime" or period == config.LIFETIME_KEY:
        return _row_to_raw(current)
    if not is_season_started(period):
        return {k: 0 for k in RAW_KEYS}
    baselines = _baseline_map(period)
    baseline = baselines.get(uuid)
    if baseline is None:
        return {k: 0 for k in RAW_KEYS}
    period_current = _current_rows_for_period(period, [current])[0]
    season = _season_raw_from_rows(period_current, baseline)
    return {k: int(season.get(k) or 0) for k in RAW_KEYS}


def tracked_player_count(period: str = "lifetime") -> int:
    if period == "lifetime":
        with _connect() as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM bba_stats").fetchone()
        return count
    return len(all_raw_rows(period))


def qualified_player_count(period: str = "lifetime") -> int:
    """Count of tracked players that meet the minimum-games bar to be ranked."""
    min_games = min_games_for_ranking(period)
    rows = all_raw_rows(period)
    return sum(1 for row in rows if (row.get("games_played") or 0) >= min_games)


def compute_percentiles(uuid: str, period: str = "lifetime") -> dict[str, dict]:
    """For each metric, return {rank, total, percentile} for the given player."""
    min_games = min_games_for_ranking(period)
    rows = [r for r in all_raw_rows(period) if (r.get("games_played") or 0) >= min_games]
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
    """Ranks every qualified tracked player for a single metric."""
    metric = METRICS.get(metric_key)
    if metric is None:
        return []

    min_games = min_games_for_ranking(period)
    rows = [r for r in all_raw_rows(period) if (r.get("games_played") or 0) >= min_games]
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
