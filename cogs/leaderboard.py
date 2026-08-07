"""/bbalb: shows the top 10 tracked players for a single Battle Box Arena stat.

Unlike the MCC Island API's own leaderboards (which only exist for 3 raw
stats -- see mcc_api.queries.LEADERBOARD_SEED_KEYS), this is computed locally
from the bot's own cached player pool (db.database), so it covers every stat
the bot tracks/derives, not just the handful with a native API leaderboard.
"""
from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import db.database as db
from cogs.rougex_gate import ROUGEX_BANNED_MESSAGE, RougeRoll, is_rougex, roll_rougex_gate
from mcc_api.client import McApiError, PlayerNotFoundError, RateLimitedError, StatisticsPrivateError, client
from render.leaderboard_card import render_leaderboard_card
from stats.derive import METRICS

log = logging.getLogger(__name__)

# Every metric the bot derives from the API (including hours played, which is
# excluded from rank *badges* on /bbastats but still makes sense as its own
# leaderboard). There are more of these than Discord's 25-item static Choice
# limit allows, so the `stat` option uses autocomplete instead of a fixed list.
_LEADERBOARD_METRIC_KEYS = list(METRICS.keys())


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _stat_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower().strip()
        matches = [
            key
            for key in _LEADERBOARD_METRIC_KEYS
            if not current_lower
            or current_lower in METRICS[key].label.lower()
            or current_lower in key.lower()
        ]
        return [app_commands.Choice(name=METRICS[key].label.lower(), value=key) for key in matches[:25]]

    @app_commands.command(name="bbalb", description="Show the top 10 tracked players for a Battle Box Arena stat.")
    @app_commands.describe(
        stat="Which stat's leaderboard to show (start typing to search).",
        username="MCC Island username whose rank to show below the top 10 (defaults to your linked account).",
        period="Show lifetime stats or Season 4 stats. Defaults to Season 4.",
    )
    @app_commands.autocomplete(stat=_stat_autocomplete)
    @app_commands.choices(
        period=[
            app_commands.Choice(name="season4", value=config.SEASON4_KEY),
            app_commands.Choice(name="lifetime", value="lifetime"),
        ]
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def bbalb(
        self,
        interaction: discord.Interaction,
        stat: str,
        username: str | None = None,
        period: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()
        period_key = period.value if period else config.SEASON4_KEY
        period_label = config.SEASON4_LABEL if period_key == config.SEASON4_KEY else "Lifetime"

        metric = METRICS.get(stat)
        if metric is None:
            await interaction.followup.send("idk what stat that is", ephemeral=True)
            return

        # Optional: pin one player's rank under the top 10. Explicit username
        # wins; otherwise fall back to the linked account. If neither is set,
        # just show the top 10 with no personal row.
        target_uuid: str | None = None
        if username and username.strip():
            gate = await asyncio.to_thread(roll_rougex_gate, username.strip(), False)
            if gate is RougeRoll.BANNED:
                await interaction.followup.send(ROUGEX_BANNED_MESSAGE, ephemeral=True)
                return
            try:
                player_stats = await asyncio.to_thread(client.get_player_stats, username.strip())
            except PlayerNotFoundError:
                await interaction.followup.send("u mispelled their username", ephemeral=True)
                return
            except StatisticsPrivateError:
                await interaction.followup.send("their statistics api is off", ephemeral=True)
                return
            except RateLimitedError:
                await interaction.followup.send("rate limited :pensive:", ephemeral=True)
                return
            except McApiError as e:
                log.exception("Error fetching player stats for /bbalb")
                await interaction.followup.send(f"uhh {e}", ephemeral=True)
                return
            if gate is None and is_rougex(player_stats.username):
                gate = await asyncio.to_thread(roll_rougex_gate, player_stats.username, False)
                if gate is RougeRoll.BANNED:
                    await interaction.followup.send(ROUGEX_BANNED_MESSAGE, ephemeral=True)
                    return
            await asyncio.to_thread(db.track_player_stats, player_stats.uuid, player_stats.username, player_stats.raw)
            target_uuid = player_stats.uuid
        else:
            linked = db.get_linked_account(str(interaction.user.id))
            if linked:
                target_uuid = linked[0]
                if is_rougex(linked[1]):
                    gate = await asyncio.to_thread(roll_rougex_gate, linked[1], False)
                    if gate is RougeRoll.BANNED:
                        await interaction.followup.send(ROUGEX_BANNED_MESSAGE, ephemeral=True)
                        return

        leaderboard = await asyncio.to_thread(db.compute_leaderboard, stat, period_key)
        top10 = leaderboard[:10]

        viewer_entry = None
        if target_uuid:
            entry = next((e for e in leaderboard if e["uuid"] == target_uuid), None)
            if entry and entry["rank"] > 10:
                viewer_entry = entry

        tracked_total = await asyncio.to_thread(db.qualified_player_count, period_key)
        min_games = db.min_games_for_ranking(period_key)

        image = await asyncio.to_thread(
            render_leaderboard_card,
            metric.label,
            top10,
            viewer_entry,
            tracked_total,
            metric.fmt,
            period_label,
            min_games,
        )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(buffer, filename=f"bba_leaderboard_{stat}.png")
        await interaction.followup.send(file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
