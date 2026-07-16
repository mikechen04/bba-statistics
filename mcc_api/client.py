"""Thin synchronous client for the MCC Island GraphQL API.

Kept synchronous (using `requests`) for simplicity; callers running inside the
Discord bot's async event loop should invoke these via `asyncio.to_thread`.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests

import config
from mcc_api.queries import LEADERBOARD_QUERY, PLAYER_PARTY_QUERY, PLAYER_STATS_QUERY, RESOLVE_PLAYER_QUERY


class McApiError(Exception):
    """Base class for all MCC Island API errors."""


class PlayerNotFoundError(McApiError):
    """Raised when the requested username doesn't resolve to a known player."""


class RateLimitedError(McApiError):
    """Raised when the API responds with a rate-limit error (HTTP 429)."""


class StatisticsPrivateError(McApiError):
    """Raised when a player hasn't enabled the in-game 'Statistics' API setting."""


@dataclass
class PlayerStats:
    uuid: str
    username: str
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> int:
        return self.raw.get(key) or 0


@dataclass
class PartyInfo:
    uuid: str
    username: str
    social_enabled: bool
    active: bool = False
    leader: dict | None = None
    members: list[dict] = field(default_factory=list)


class McIslandClient:
    # The API allows 3 requests/second; leave a little headroom below that so
    # multi-request operations (leaderboard crawls, party-member caching) don't
    # trip the rate limiter when they fire several requests back-to-back.
    _MIN_REQUEST_INTERVAL = 0.4

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "X-API-Key": config.MCC_API_KEY,
                "Content-Type": "application/json",
                "User-Agent": config.MCC_USER_AGENT,
            }
        )
        self._throttle_lock = threading.Lock()
        self._last_request_at = 0.0

    def _post(self, query: str, variables: dict[str, Any], _retries: int = 3) -> dict[str, Any]:
        for attempt in range(_retries + 1):
            with self._throttle_lock:
                wait = self._MIN_REQUEST_INTERVAL - (time.monotonic() - self._last_request_at)
                if wait > 0:
                    time.sleep(wait)
                self._last_request_at = time.monotonic()

            response = self._session.post(
                config.MCC_API_URL,
                json={"query": query, "variables": variables},
                timeout=15,
            )
            if response.status_code == 429:
                if attempt < _retries:
                    # Bulk operations (leaderboard crawls, party caching) can still
                    # occasionally overlap with other in-flight requests despite the
                    # client-side throttle above; briefly back off and retry rather
                    # than failing the whole operation.
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RateLimitedError("The MCC Island API is rate-limiting this bot right now. Try again shortly.")
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                messages = "; ".join(e.get("message", "unknown error") for e in payload["errors"])
                raise McApiError(f"MCC Island API returned an error: {messages}")
            return payload.get("data") or {}
        raise RateLimitedError("The MCC Island API is rate-limiting this bot right now. Try again shortly.")

    def resolve_username(self, username: str) -> tuple[str, str]:
        """Return (uuid, canonical_username) for a username, or raise PlayerNotFoundError."""
        data = self._post(RESOLVE_PLAYER_QUERY, {"username": username})
        player = data.get("playerByUsername")
        if not player:
            raise PlayerNotFoundError(f"No MCC Island player found with the username \"{username}\".")
        return player["uuid"], player["username"]

    def get_player_stats(self, username: str) -> PlayerStats:
        data = self._post(PLAYER_STATS_QUERY, {"username": username})
        player = data.get("playerByUsername")
        if not player:
            raise PlayerNotFoundError(f"No MCC Island player found with the username \"{username}\".")
        statistics = player.get("statistics")
        if statistics is None:
            raise StatisticsPrivateError(
                f"{player['username']} hasn't enabled the in-game 'Statistics' API setting."
            )
        return PlayerStats(uuid=player["uuid"], username=player["username"], raw=statistics)

    def get_leaderboard(self, stat_key: str, rotation: str = "LIFETIME", page_size: int = 50) -> list[PlayerStats]:
        """Crawls a public statistic leaderboard from the top down, returning the
        full BBA statistics block for every player encountered.

        The API's leaderboard depth is capped internally (observed to top out
        around rank ~100, regardless of `amount`/`offset` requested), so this
        can only ever seed the local cache with top-performing players for
        `stat_key`, not "every player on MCC Island" -- there's no endpoint
        that enumerates the full player base. See db.database module docs.
        """
        results: list[PlayerStats] = []
        seen_uuids: set[str] = set()
        highest_rank_seen = 0
        offset = 0
        for _ in range(10):  # safety cap on pages; real leaderboards stop far sooner
            data = self._post(
                LEADERBOARD_QUERY,
                {"key": stat_key, "rotation": rotation, "amount": page_size, "offset": offset},
            )
            entries = (data.get("statistic") or {}).get("leaderboard") or []
            entries = [e for e in entries if (e.get("rank") or 0) > highest_rank_seen]
            if not entries:
                break
            for entry in entries:
                player = entry.get("player")
                if not player or player["uuid"] in seen_uuids:
                    continue
                seen_uuids.add(player["uuid"])
                results.append(
                    PlayerStats(uuid=player["uuid"], username=player["username"], raw=player.get("statistics") or {})
                )
            highest_rank_seen = max(e["rank"] for e in entries)
            offset += page_size
        return results

    def get_player_party(self, username: str) -> PartyInfo:
        data = self._post(PLAYER_PARTY_QUERY, {"username": username})
        player = data.get("playerByUsername")
        if not player:
            raise PlayerNotFoundError(f"No MCC Island player found with the username \"{username}\".")
        social = player.get("social")
        if social is None:
            return PartyInfo(uuid=player["uuid"], username=player["username"], social_enabled=False)
        party = social.get("party") or {}
        return PartyInfo(
            uuid=player["uuid"],
            username=player["username"],
            social_enabled=True,
            active=bool(party.get("active")),
            leader=party.get("leader"),
            members=party.get("members") or [],
        )


client = McIslandClient()
