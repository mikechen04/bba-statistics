"""Personal-touch gate for one specific username (display-only shenanigans).

Never mutates tracked BBA stats. Ban state lives in bot_meta and clears on a
later 1-2 roll, so it stays temporary and reversible.
"""
from __future__ import annotations

import random
from enum import Enum

import db.database as db
from stats.derive import METRICS

ROUGEX_USERNAME = "rougex15"
_BAN_META_KEY = "temp_display_ban:rougex15"


class RougeRoll(Enum):
    NORMAL = "normal"
    SIXTY_SEVEN = "sixty_seven"
    BANNED = "banned"


def is_rougex(username: str | None) -> bool:
    return bool(username) and username.lower() == ROUGEX_USERNAME


def is_rougex_banned() -> bool:
    return db.get_meta(_BAN_META_KEY) is not None


def clear_rougex_ban() -> None:
    db.delete_meta(_BAN_META_KEY)


def _set_rougex_ban() -> None:
    from datetime import datetime, timezone

    db.set_meta(_BAN_META_KEY, datetime.now(timezone.utc).isoformat())


def roll_rougex_gate(username: str | None, allow_sixty_seven: bool = True) -> RougeRoll | None:
    """Roll a d6 for rougex15 lookups. Returns None for every other username.

    1-2: show real stats (and clear any temp ban)
    3-5: show 67-themed fake stats when allow_sixty_seven, else treat as normal
    6: temp-ban (reversible on a later 1-2)
    While banned, only 1-2 unbans and shows; 3-6 stay blocked.
    """
    if not is_rougex(username):
        return None

    roll = random.randint(1, 6)
    banned = is_rougex_banned()

    if roll <= 2:
        if banned:
            clear_rougex_ban()
        return RougeRoll.NORMAL

    if banned:
        return RougeRoll.BANNED

    if roll <= 5:
        return RougeRoll.SIXTY_SEVEN if allow_sixty_seven else RougeRoll.NORMAL

    _set_rougex_ban()
    return RougeRoll.BANNED


def sixty_seven_metric_values() -> dict[str, float]:
    """Display-only metric map: every value is a variation on 67."""
    values: dict[str, float] = {}
    for key, metric in METRICS.items():
        sample = metric.fmt(12.34)
        if sample.endswith("%"):
            values[key] = 67.0
        elif sample.endswith("h"):
            values[key] = 67.0
        elif "." in sample:
            values[key] = 6.7
        else:
            values[key] = 67.0
    # Keep the damage bar coherent while staying on-theme.
    values["melee_pct"] = 67.0
    values["ranged_pct"] = 33.0
    return values


def sixty_seven_percentiles() -> dict[str, dict]:
    return {
        key: {"rank": 67, "total": 67, "percentile": 67.0}
        for key, metric in METRICS.items()
        if metric.rankable
    }


ROUGEX_BANNED_MESSAGE = "rougex15 is temporarily banned from the bot (roll a 1-2 next time to unban)"
