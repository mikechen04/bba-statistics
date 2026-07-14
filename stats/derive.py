"""Derives display-ready Battle Box Arena metrics from raw API statistics.

Every raw stat comes straight from the MCC Island API (see mcc_api/queries.py).
Everything here (WLR, K/D, per-game/per-round rates, percentages) is math we
compute ourselves, since the API only exposes the raw counters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

RAW_KEYS = (
    "games_played",
    "games_won",
    "rounds_played",
    "rounds_won",
    "kills",
    "deaths",
    "assists",
    "aces",
    "wool_placed",
    "wool_broken",
    "top1",
    "top3",
    "melee_kills",
    "ranged_kills",
    "score",
)


def safe_div(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    compute: Callable[[dict], float]
    fmt: Callable[[float], str]
    direction: str = "desc"  # "desc": higher is better. "asc": lower is better.
    rankable: bool = True


def _int_fmt(v: float) -> str:
    return f"{int(round(v)):,}"


def _dec_fmt(v: float) -> str:
    return f"{v:.2f}"


def _pct_fmt(v: float) -> str:
    return f"{v:.1f}%"


METRICS: dict[str, Metric] = {
    m.key: m
    for m in [
        Metric("games_played", "Games Played", lambda r: r["games_played"], _int_fmt),
        Metric("games_won", "Games Won", lambda r: r["games_won"], _int_fmt),
        Metric(
            "wlr",
            "WLR",
            lambda r: safe_div(r["games_won"], max(r["games_played"] - r["games_won"], 0)),
            _dec_fmt,
        ),
        Metric("kd", "K/D", lambda r: safe_div(r["kills"], r["deaths"]), _dec_fmt),
        Metric("kills_per_game", "Kills Per Game", lambda r: safe_div(r["kills"], r["games_played"]), _dec_fmt),
        Metric("kills_per_round", "Kills Per Round", lambda r: safe_div(r["kills"], r["rounds_played"]), _dec_fmt),
        Metric("total_kills", "Total Kills", lambda r: r["kills"], _int_fmt),
        Metric(
            "deaths_per_game", "Deaths Per Game", lambda r: safe_div(r["deaths"], r["games_played"]), _dec_fmt,
            direction="asc",
        ),
        Metric(
            "deaths_per_round", "Deaths Per Round", lambda r: safe_div(r["deaths"], r["rounds_played"]), _dec_fmt,
            direction="asc",
        ),
        Metric("total_deaths", "Total Deaths", lambda r: r["deaths"], _int_fmt, direction="asc"),
        Metric(
            "assists_per_game", "Assists Per Game", lambda r: safe_div(r["assists"], r["games_played"]), _dec_fmt
        ),
        Metric(
            "assists_per_round", "Assists Per Round", lambda r: safe_div(r["assists"], r["rounds_played"]), _dec_fmt
        ),
        Metric("total_assists", "Total Assists", lambda r: r["assists"], _int_fmt),
        Metric("aces_per_game", "Aces Per Game", lambda r: safe_div(r["aces"], r["games_played"]), _dec_fmt),
        Metric("aces_per_round", "Aces Per Round", lambda r: safe_div(r["aces"], r["rounds_played"]), _dec_fmt),
        Metric("total_aces", "Total Aces", lambda r: r["aces"], _int_fmt),
        Metric("wool_placed", "Wool Placed", lambda r: r["wool_placed"], _int_fmt),
        Metric("wool_broken", "Wool Broken", lambda r: r["wool_broken"], _int_fmt),
        Metric(
            "top1_pct", "Top 1 Placement %", lambda r: safe_div(r["top1"], r["games_played"]) * 100, _pct_fmt
        ),
        Metric("total_top1", "Total Top 1", lambda r: r["top1"], _int_fmt),
        Metric(
            "top3_pct", "Top 3 Placement %", lambda r: safe_div(r["top3"], r["games_played"]) * 100, _pct_fmt
        ),
        Metric("total_top3", "Total Top 3", lambda r: r["top3"], _int_fmt),
        Metric(
            "melee_pct", "Melee Kill %", lambda r: safe_div(r["melee_kills"], r["kills"]) * 100, _pct_fmt
        ),
        Metric(
            "ranged_pct", "Ranged Kill %", lambda r: safe_div(r["ranged_kills"], r["kills"]) * 100, _pct_fmt
        ),
        Metric(
            "round_win_pct",
            "Round Win %",
            lambda r: safe_div(r["rounds_won"], r["rounds_played"]) * 100,
            _pct_fmt,
        ),
        Metric("total_rounds_played", "Total Rounds Played", lambda r: r["rounds_played"], _int_fmt),
        Metric("coins_per_game", "Coins Per Game", lambda r: safe_div(r["score"], r["games_played"]), _dec_fmt),
        Metric("coins_per_round", "Coins Per Round", lambda r: safe_div(r["score"], r["rounds_played"]), _dec_fmt),
        Metric("total_coins", "Total Coins", lambda r: r["score"], _int_fmt),
    ]
}


def compute_all(raw: dict) -> dict[str, float]:
    """Compute every derived metric value from a raw stats dict."""
    safe_raw = {k: raw.get(k) or 0 for k in RAW_KEYS}
    return {key: metric.compute(safe_raw) for key, metric in METRICS.items()}
