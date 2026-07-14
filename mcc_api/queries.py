"""GraphQL query strings for the MCC Island API (https://api.mccisland.net/docs)."""

# The raw Battle Box Arena statistic keys we read for every lookup. Every key
# below is confirmed to track the LIFETIME rotation via the `statistics` query.
BBA_STAT_KEYS = {
    "games_played": "battle_box_arena_games_played",
    "games_won": "battle_box_arena_team_first_place",
    "rounds_played": "battle_box_arena_rounds_played",
    "rounds_won": "battle_box_arena_team_rounds_won",
    "kills": "battle_box_arena_players_killed",
    "deaths": "battle_box_arena_times_eliminated",
    "assists": "battle_box_arena_player_kills_assisted",
    "aces": "battle_box_arena_ace",
    "wool_placed": "battle_box_arena_wool_placed",
    "wool_broken": "battle_box_arena_enemy_wool_broken",
    "top1": "battle_box_arena_first_place_individual",
    "top3": "battle_box_arena_top_three_individual",
    "melee_kills": "battle_box_arena_melee_kills",
    "ranged_kills": "battle_box_arena_ranged_kills",
    # The API has no "coins" stat scoped to a specific gamemode -- only an
    # overall account-wide coin balance. However, `total_score_earned` tracks
    # essentially the same thing under the hood (confirmed by cross-checking
    # its per-game rate against a known coins-per-game value), so we surface
    # it as the closest available equivalent, labeled accordingly in the UI.
    "score": "battle_box_arena_total_score_earned",
}

_stat_fields = "\n".join(
    f'      {alias}: rotationValue(statisticKey: "{key}", rotation: LIFETIME)'
    for alias, key in BBA_STAT_KEYS.items()
)

PLAYER_STATS_QUERY = f"""
query PlayerStats($username: String!) {{
  playerByUsername(username: $username) {{
    uuid
    username
    statistics {{
{_stat_fields}
    }}
  }}
}}
"""

PLAYER_PARTY_QUERY = """
query PlayerParty($username: String!) {
  playerByUsername(username: $username) {
    uuid
    username
    social {
      party {
        active
        leader { uuid username }
        members { uuid username }
      }
    }
  }
}
"""

RESOLVE_PLAYER_QUERY = """
query ResolvePlayer($username: String!) {
  playerByUsername(username: $username) {
    uuid
    username
  }
}
"""
