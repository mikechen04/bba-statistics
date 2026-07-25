"""Radar-chart axes and normalization for /bbaradar.

Each axis maps a derived BBA metric onto a 0-100 scale using a soft ceiling
(values at/above the ceiling clamp to 100). Ceilings are tuned near the
Expert LFG bar so a strong player fills most of the chart without every
casual profile looking empty.
"""
from __future__ import annotations

from dataclasses import dataclass

from stats.derive import METRICS, compute_all


@dataclass(frozen=True)
class RadarAxis:
    key: str           # short id used internally
    label: str         # axis label drawn on the chart
    metric_key: str    # key into compute_all() / METRICS
    ceiling: float     # raw value that maps to 100 on the radar
    blurb: str         # one-line definition shown in the footer legend
    short: str         # compact label used in the side stat panels


RADAR_AXES: tuple[RadarAxis, ...] = (
    RadarAxis("fragging", "Fragging", "kills_per_game", 7.0, "kills / game", "FRAG"),
    RadarAxis("sustain", "Sustain", "kd", 3.0, "K/D ratio", "SUS"),
    RadarAxis("team", "Team Play", "assists_per_game", 5.0, "assists / game", "TEAM"),
    RadarAxis("consistency", "Consistency", "round_win_pct", 75.0, "round win %", "CONS"),
    RadarAxis("placement", "Placement", "top3_pct", 85.0, "top 3 placement %", "T3"),
    RadarAxis("economy", "Economy", "coins_per_game", 450.0, "coins / game", "ECO"),
)


# Extra compact stats shown in the player panels (beyond the six radar axes).
PANEL_EXTRAS: tuple[tuple[str, str], ...] = (
    ("WLR", "wlr"),
    ("GAMES", "games_played"),
)


def normalize(value: float, ceiling: float) -> float:
    if ceiling <= 0:
        return 0.0
    return max(0.0, min(100.0, (value / ceiling) * 100.0))


def radar_scores(raw: dict) -> dict[str, float]:
    """Return {axis_key: 0-100 score} for every radar axis."""
    values = compute_all(raw)
    return {
        axis.key: normalize(values[axis.metric_key], axis.ceiling)
        for axis in RADAR_AXES
    }


def panel_stats(raw: dict) -> list[tuple[str, str]]:
    """Compact (label, formatted_value) pairs for a player's side panel."""
    values = compute_all(raw)
    rows = [(axis.short, METRICS[axis.metric_key].fmt(values[axis.metric_key])) for axis in RADAR_AXES]
    for short, metric_key in PANEL_EXTRAS:
        rows.append((short, METRICS[metric_key].fmt(values[metric_key])))
    return rows
