"""Radar-chart axes and normalization for /bbaradar.

Each axis maps a core derived BBA metric onto a shared 0-100 scale. When a
reference pool of tracked players is available, every axis is normalized the
same way: as a percentile among that pool (higher fill = better relative to
tracked players). Fixed soft ceilings remain only as a fallback when the pool
is empty.
"""
from __future__ import annotations

from dataclasses import dataclass

from stats.derive import METRICS, compute_all


@dataclass(frozen=True)
class RadarAxis:
    key: str  # short id used internally
    label: str  # axis label drawn on the chart
    metric_key: str  # key into compute_all() / METRICS
    ceiling: float  # fallback raw value that maps to 100 when no pool exists
    blurb: str  # one-line definition shown in the footer legend
    short: str  # compact label used in the side stat panels


RADAR_AXES: tuple[RadarAxis, ...] = (
    RadarAxis("fragging", "Fragging", "kills_per_game", 7.0, "kills / game", "FRAG"),
    RadarAxis("sustain", "Sustain", "kd", 3.0, "K/D ratio", "SUS"),
    RadarAxis("team", "Team Play", "assists_per_game", 5.0, "assists / game", "TEAM"),
    RadarAxis("consistency", "Consistency", "round_win_pct", 75.0, "round win %", "CONS"),
    RadarAxis("placement", "Placement", "top3_pct", 85.0, "top 3 placement %", "T3"),
    RadarAxis("economy", "Economy", "coins_per_game", 450.0, "coins / game", "ECO"),
)


def normalize_ceiling(value: float, ceiling: float) -> float:
    if ceiling <= 0:
        return 0.0
    return max(0.0, min(100.0, (value / ceiling) * 100.0))


def normalize_percentile(value: float, pool_values: list[float], direction: str = "desc") -> float:
    """Map `value` onto 0-100 from its standing in `pool_values`.

    Higher score always means better. For ascending metrics (lower is better),
    the score rises as fewer players beat you.
    """
    if not pool_values:
        return 0.0
    if direction == "asc":
        # Lower is better: count how many are as bad or worse (value >= yours).
        count = sum(1 for v in pool_values if v >= value)
    else:
        # Higher is better: count how many are as weak or weaker (value <= yours).
        count = sum(1 for v in pool_values if v <= value)
    return max(0.0, min(100.0, count / len(pool_values) * 100.0))


def _pool_metric_values(pool_computed: list[dict[str, float]], metric_key: str) -> list[float]:
    return [row[metric_key] for row in pool_computed]


def radar_scores(
    raw: dict,
    reference_rows: list[dict] | None = None,
    pool_computed: list[dict[str, float]] | None = None,
) -> dict[str, float]:
    """Return {axis_key: 0-100 score} for every radar axis.

    Prefer pool-relative percentiles so every core axis shares one normalized
    scale. Falls back to per-axis soft ceilings when no reference pool is given.
    """
    values = compute_all(raw)

    computed_pool = pool_computed
    if computed_pool is None and reference_rows:
        computed_pool = [compute_all(row) for row in reference_rows]

    if not computed_pool:
        return {
            axis.key: normalize_ceiling(values[axis.metric_key], axis.ceiling)
            for axis in RADAR_AXES
        }

    scores: dict[str, float] = {}
    for axis in RADAR_AXES:
        metric = METRICS[axis.metric_key]
        pool_vals = _pool_metric_values(computed_pool, axis.metric_key)
        scores[axis.key] = normalize_percentile(
            values[axis.metric_key],
            pool_vals,
            direction=metric.direction,
        )
    return scores


def radar_scores_for_players(
    raws: list[dict],
    reference_rows: list[dict] | None = None,
) -> list[dict[str, float]]:
    """Normalize several players against one shared reference pool."""
    pool_computed = [compute_all(row) for row in reference_rows] if reference_rows else None
    return [radar_scores(raw, pool_computed=pool_computed) for raw in raws]


def panel_stats(raw: dict) -> list[tuple[str, str]]:
    """Compact (label, formatted_value) pairs — raw metric values, one per axis."""
    values = compute_all(raw)
    return [(axis.short, METRICS[axis.metric_key].fmt(values[axis.metric_key])) for axis in RADAR_AXES]
