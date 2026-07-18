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

import db.database as db
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
        return [app_commands.Choice(name=METRICS[key].label, value=key) for key in matches[:25]]

    @app_commands.command(name="bbalb", description="Show the top 10 tracked players for a Battle Box Arena stat.")
    @app_commands.describe(stat="Which stat's leaderboard to show (start typing to search).")
    @app_commands.autocomplete(stat=_stat_autocomplete)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def bbalb(self, interaction: discord.Interaction, stat: str) -> None:
        await interaction.response.defer()

        metric = METRICS.get(stat)
        if metric is None:
            await interaction.followup.send(
                "Unknown stat. Start typing in the `stat` option to pick one from the suggestions.",
                ephemeral=True,
            )
            return

        leaderboard = await asyncio.to_thread(db.compute_leaderboard, stat)
        top10 = leaderboard[:10]

        # Only surface the requesting user's own rank if they're linked (per
        # their request, no username option here -- it's always "your" rank).
        # Silently omit it if they're not linked, not tracked, or already in
        # the top 10 shown above.
        viewer_entry = None
        linked = db.get_linked_account(str(interaction.user.id))
        if linked:
            linked_uuid = linked[0]
            entry = next((e for e in leaderboard if e["uuid"] == linked_uuid), None)
            if entry and entry["rank"] > 10:
                viewer_entry = entry

        tracked_total = await asyncio.to_thread(db.qualified_player_count)

        image = await asyncio.to_thread(
            render_leaderboard_card, metric.label, top10, viewer_entry, tracked_total, metric.fmt
        )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(buffer, filename=f"bba_leaderboard_{stat}.png")
        await interaction.followup.send(file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
