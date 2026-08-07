"""Personal-touch gate for one specific username (display-only shenanigans).

Never mutates tracked BBA stats. A roll of 6 only blocks that single lookup;
the next check rolls again, so it stays temporary and reversible.
"""
from __future__ import annotations

import random
from enum import Enum

from stats.derive import METRICS

ROUGEX_USERNAME = "rougex15"


class RougeRoll(Enum):
    NORMAL = "normal"
    SIXTY_SEVEN = "sixty_seven"
    BANNED = "banned"


def is_rougex(username: str | None) -> bool:
    return bool(username) and username.lower() == ROUGEX_USERNAME


def is_rougex_banned() -> bool:
    # Kept for callers that filter leaderboards; bans are per-lookup only now.
    return False


def roll_rougex_gate(username: str | None, allow_sixty_seven: bool = True) -> RougeRoll | None:
    """Roll a d6 for rougex15 lookups. Returns None for every other username.

    1-2: show real stats
    3-5: show 67-themed fake stats when allow_sixty_seven, else treat as normal
    6: block this lookup only (next check rolls fresh)
    """
    if not is_rougex(username):
        return None

    roll = random.randint(1, 6)
    if roll <= 2:
        return RougeRoll.NORMAL
    if roll <= 5:
        return RougeRoll.SIXTY_SEVEN if allow_sixty_seven else RougeRoll.NORMAL
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


ROUGEX_BANNED_MESSAGE = "rougex15 got banned from this lookup (try again)"
