"""/bbastats: renders a player's Battle Box Arena stat card as an image."""
from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import db.database as db
from cogs.common import UserFacingError, resolve_target_username
from cogs.rougex_gate import (
    RougeRoll,
    banned_message,
    is_rougex,
    roll_rougex_gate,
    sixty_seven_metric_values,
    sixty_seven_percentiles,
)
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
        display="Show ranks as position numbers (#1) or percentiles (0.1%). Defaults to numbers.",
        period="Show lifetime stats or Season 4 stats. Defaults to Season 4.",
    )
    @app_commands.choices(
        display=[
            app_commands.Choice(name="numbers", value="number"),
            app_commands.Choice(name="percentile", value="percentile"),
        ],
        period=[
            app_commands.Choice(name="season4", value=config.SEASON4_KEY),
            app_commands.Choice(name="lifetime", value="lifetime"),
        ],
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def bbastats(
        self,
        interaction: discord.Interaction,
        username: str | None = None,
        display: app_commands.Choice[str] | None = None,
        period: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()
        rank_mode = display.value if display else "number"
        period_key = period.value if period else config.SEASON4_KEY
        period_label = config.SEASON4_LABEL if period_key == config.SEASON4_KEY else "Lifetime"

        try:
            target = await resolve_target_username(interaction, username)
        except UserFacingError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        gate = await asyncio.to_thread(roll_rougex_gate, target)
        if gate is not None and gate.outcome is RougeRoll.BANNED:
            await interaction.followup.send(banned_message(gate.dice), ephemeral=True)
            return

        try:
            player_stats = await asyncio.to_thread(client.get_player_stats, target)
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
            log.exception("Error fetching player stats")
            await interaction.followup.send(f"uhh {e}", ephemeral=True)
            return

        # If the user typed a non-rougex alias but the account resolves to rougex15,
        # roll once now (we skipped earlier because `target` wasn't him).
        if gate is None and is_rougex(player_stats.username):
            gate = await asyncio.to_thread(roll_rougex_gate, player_stats.username)
            if gate is not None and gate.outcome is RougeRoll.BANNED:
                await interaction.followup.send(banned_message(gate.dice), ephemeral=True)
                return

        await asyncio.to_thread(db.track_player_stats, player_stats.uuid, player_stats.username, player_stats.raw)
        raw_for_card = await asyncio.to_thread(db.get_player_raw, player_stats.uuid, period_key)
        percentiles = await asyncio.to_thread(db.compute_percentiles, player_stats.uuid, period_key)
        tracked_total = await asyncio.to_thread(db.qualified_player_count, period_key)
        min_games = db.min_games_for_ranking(period_key)

        values_override = None
        if gate is not None and gate.outcome is RougeRoll.SIXTY_SEVEN:
            values_override = sixty_seven_metric_values()
            percentiles = sixty_seven_percentiles()

        display_username = theme.DISPLAY_NAME_OVERRIDES.get(player_stats.username.lower(), player_stats.username)

        # Heart badges key off the real IGN; display name may be overridden (e.g. rougex).
        image = await asyncio.to_thread(
            render_stats_card,
            display_username,
            player_stats.uuid,
            raw_for_card,
            percentiles,
            tracked_total,
            rank_mode,
            period_label,
            min_games,
            values_override,
            heart_username=player_stats.username,
        )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(buffer, filename=f"{target}_bba_stats.png")
        if gate is not None:
            await interaction.followup.send(gate.announce(), file=file)
        else:
            await interaction.followup.send(file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
