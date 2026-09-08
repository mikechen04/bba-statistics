"""Centralized configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
FONTS_DIR = BASE_DIR / "render" / "fonts"

DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID") or None

# Comma-separated Discord user IDs allowed to use the private DM "servers" command.
# If empty, falls back to the Discord application owner only.
_OWNER_RAW = os.getenv("OWNER_DISCORD_ID", "") or os.getenv("OWNER_DISCORD_IDS", "")
OWNER_DISCORD_IDS: set[int] = {
    int(piece.strip()) for piece in _OWNER_RAW.split(",") if piece.strip().isdigit()
}

MCC_API_KEY = os.getenv("MCC_API_KEY", "")
CONTACT_INFO = os.getenv("CONTACT_INFO", "unknown")
MCC_API_URL = "https://api.mccisland.net/graphql"
MCC_USER_AGENT = f"bba-statistics-discord-bot (contact: {CONTACT_INFO})"

DB_PATH = DATA_DIR / "bba.sqlite3"
MATCH_HISTORY_PATH = Path(os.getenv("MATCH_HISTORY_PATH", DATA_DIR / "battlebox-qol-match-history.json"))

GAME = "BATTLE_BOX_ARENA"

BOT_TIMEZONE = timezone(timedelta(hours=9), name="JST")

# Sep 8, 2026 is during US daylight saving, so Eastern Time is EDT (UTC-4).
# "6am EST" in the season cutoff means 6:00 AM Eastern that morning.
EASTERN_EDT = timezone(timedelta(hours=-4), name="EDT")

LIFETIME_KEY = "lifetime"
LIFETIME_LABEL = "Lifetime"


@dataclass(frozen=True)
class StatPeriod:
    """A named stats window: lifetime-minus-baseline while open, frozen after end_at."""

    key: str
    label: str
    choice_name: str
    start_at: datetime
    end_at: datetime | None = None


SEASON4 = StatPeriod(
    key="season4",
    label="Season 4",
    choice_name="season4",
    start_at=datetime(2026, 7, 28, 19, 0, tzinfo=BOT_TIMEZONE),
    # Inclusive of games through 5:59 AM Eastern; off-season starts at 6:00 AM.
    end_at=datetime(2026, 9, 8, 6, 0, tzinfo=EASTERN_EDT),
)
S4_OFFSEASON = StatPeriod(
    key="s4offseason",
    label="S4 Off-Season",
    choice_name="s4 off-season",
    start_at=SEASON4.end_at,
    end_at=None,
)

STAT_PERIODS: dict[str, StatPeriod] = {
    SEASON4.key: SEASON4,
    S4_OFFSEASON.key: S4_OFFSEASON,
}

# Backward-compatible aliases used throughout the bot.
SEASON4_KEY = SEASON4.key
SEASON4_LABEL = SEASON4.label
SEASON4_START_AT = SEASON4.start_at
SEASON4_END_AT = SEASON4.end_at
S4_OFFSEASON_KEY = S4_OFFSEASON.key
S4_OFFSEASON_LABEL = S4_OFFSEASON.label
S4_OFFSEASON_START_AT = S4_OFFSEASON.start_at


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def get_period(key: str) -> StatPeriod | None:
    return STAT_PERIODS.get(key)


def period_label(key: str) -> str:
    if key == LIFETIME_KEY:
        return LIFETIME_LABEL
    period = STAT_PERIODS.get(key)
    return period.label if period else key


def next_period(period_key: str) -> StatPeriod | None:
    """The period that starts exactly when `period_key` ends, if any."""
    period = STAT_PERIODS.get(period_key)
    if period is None or period.end_at is None:
        return None
    end = _utc(period.end_at)
    for candidate in STAT_PERIODS.values():
        if candidate.key != period.key and _utc(candidate.start_at) == end:
            return candidate
    return None


def previous_period(period_key: str) -> StatPeriod | None:
    """The period that ended exactly when `period_key` starts, if any."""
    period = STAT_PERIODS.get(period_key)
    if period is None:
        return None
    start = _utc(period.start_at)
    for candidate in STAT_PERIODS.values():
        if candidate.key != period.key and candidate.end_at is not None and _utc(candidate.end_at) == start:
            return candidate
    return None


def default_period_key(now: datetime | None = None) -> str:
    """Latest open seasonal period, else the latest started one, else lifetime."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    started = [p for p in STAT_PERIODS.values() if current >= _utc(p.start_at)]
    if not started:
        return LIFETIME_KEY
    open_periods = [p for p in started if p.end_at is None or current < _utc(p.end_at)]
    pool = open_periods or started
    return max(pool, key=lambda p: _utc(p.start_at)).key


def period_choice_values() -> list[tuple[str, str]]:
    """Discord slash-command (name, value) pairs, newest seasonal period first."""
    items = [
        (p.choice_name, p.key)
        for p in sorted(STAT_PERIODS.values(), key=lambda p: _utc(p.start_at), reverse=True)
    ]
    items.append((LIFETIME_KEY, LIFETIME_KEY))
    return items
