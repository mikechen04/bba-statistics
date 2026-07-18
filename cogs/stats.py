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
from render import theme
from render.stats_card import render_stats_card

log = logging.getLogger(__name__)


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="bbastats", description="Show a player's Battle Box Arena statistics.")
    @app_commands.describe(
        username="MCC Island username to look up (defaults to your linked account).",
        rank_display="Show ranks as position numbers (#1) or percentiles (0.1%). Defaults to numbers.",
    )
    @app_commands.choices(
        rank_display=[
            app_commands.Choice(name="Number (#1, #2, ...)", value="number"),
            app_commands.Choice(name="Percentile (0.1%, 12.5%, ...)", value="percentile"),
        ]
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def bbastats(
        self,
        interaction: discord.Interaction,
        username: str | None = None,
        rank_display: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()
        rank_mode = rank_display.value if rank_display else "number"

        try:
            target = await resolve_target_username(interaction, username)
        except UserFacingError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        try:
            player_stats = await asyncio.to_thread(client.get_player_stats, target)
        except PlayerNotFoundError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except StatisticsPrivateError as e:
            await interaction.followup.send(
                f"{e} They need to enable the **Statistics** API setting in-game "
                "(MCC Island settings menu) before their stats can be viewed here.",
                ephemeral=True,
            )
            return
        except RateLimitedError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except McApiError as e:
            log.exception("Error fetching player stats")
            await interaction.followup.send(
                f"Something went wrong talking to the MCC Island API: {e}", ephemeral=True
            )
            return

        await asyncio.to_thread(db.upsert_player_stats, player_stats.uuid, player_stats.username, player_stats.raw)
        percentiles = await asyncio.to_thread(db.compute_percentiles, player_stats.uuid)
        tracked_total = await asyncio.to_thread(db.qualified_player_count)

        display_username = theme.DISPLAY_NAME_OVERRIDES.get(player_stats.username.lower(), player_stats.username)

        image = await asyncio.to_thread(
            render_stats_card,
            display_username,
            player_stats.uuid,
            player_stats.raw,
            percentiles,
            tracked_total,
            rank_mode,
        )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(buffer, filename=f"{target}_bba_stats.png")
        await interaction.followup.send(file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
