"""/bbastats: renders a player's Battle Box Arena stat card as an image."""
from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

import db.database as db
from cogs.common import UserFacingError, resolve_target_username
from mcc_api.client import McApiError, PlayerNotFoundError, RateLimitedError, StatisticsPrivateError, client
from render.stats_card import render_stats_card

log = logging.getLogger(__name__)


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="bbastats", description="Show a player's Battle Box Arena statistics.")
    @app_commands.describe(username="MCC Island username to look up (defaults to your linked account).")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def bbastats(self, interaction: discord.Interaction, username: str | None = None) -> None:
        await interaction.response.defer()

        try:
            target = await resolve_target_username(interaction, username)
        except UserFacingError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        # Joke card: always shows fake numbers for this specific player, regardless of
        # their real stats/privacy settings, and never touches the shared tracking DB.
        is_joke_target = target.lower() == "rougex15"

        try:
            player_stats = await asyncio.to_thread(client.get_player_stats, target)
        except PlayerNotFoundError as e:
            if not is_joke_target:
                await interaction.followup.send(str(e), ephemeral=True)
                return
            player_stats = None
        except StatisticsPrivateError as e:
            if not is_joke_target:
                await interaction.followup.send(
                    f"{e} They need to enable the **Statistics** API setting in-game "
                    "(MCC Island settings menu) before their stats can be viewed here.",
                    ephemeral=True,
                )
                return
            player_stats = None
        except RateLimitedError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except McApiError as e:
            if not is_joke_target:
                log.exception("Error fetching player stats")
                await interaction.followup.send(
                    f"Something went wrong talking to the MCC Island API: {e}", ephemeral=True
                )
                return
            player_stats = None

        if is_joke_target:
            display_username = player_stats.username if player_stats else target
            uuid = player_stats.uuid if player_stats else "00000000-0000-0000-0000-000000000000"
            image = await asyncio.to_thread(render_stats_card, display_username, uuid, {}, {}, 0)
        else:
            await asyncio.to_thread(db.upsert_player_stats, player_stats.uuid, player_stats.username, player_stats.raw)
            percentiles = await asyncio.to_thread(db.compute_percentiles, player_stats.uuid)
            tracked_total = await asyncio.to_thread(db.tracked_player_count)

            image = await asyncio.to_thread(
                render_stats_card, player_stats.username, player_stats.uuid, player_stats.raw, percentiles, tracked_total
            )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(buffer, filename=f"{target}_bba_stats.png")
        await interaction.followup.send(file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
