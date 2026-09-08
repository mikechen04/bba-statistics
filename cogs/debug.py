"""Owner-only /debug helpers for tuning /bbastats name colors."""
from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import db.database as db
from mcc_api.client import McApiError, PlayerNotFoundError, RateLimitedError, StatisticsPrivateError, client
from render import theme
from render.name_colors import named_color_choices, parse_color
from render.stats_card import render_stats_card

log = logging.getLogger(__name__)


async def _is_owner(interaction: discord.Interaction) -> bool:
    if config.OWNER_DISCORD_IDS:
        return interaction.user.id in config.OWNER_DISCORD_IDS
    return await interaction.client.is_owner(interaction.user)


class DebugCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="debug",
        description="Owner-only: set a custom /bbastats name color for a username.",
    )
    @app_commands.describe(
        username="MCC Island username to color on /bbastats.",
        color="Named color, #hex, r,g,b, or clear to remove your override.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def debug(self, interaction: discord.Interaction, username: str, color: str) -> None:
        if not await _is_owner(interaction):
            await interaction.response.send_message("not allowed", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        parsed = parse_color(color)
        if isinstance(parsed, str):
            await interaction.followup.send(
                f"{parsed}\n\nnames: {named_color_choices()}\nhex: `#c4a5e3`\nrgb: `196,165,227`",
                ephemeral=True,
            )
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
            log.exception("Error fetching player stats for /debug")
            await interaction.followup.send(f"uhh {e}", ephemeral=True)
            return

        ign = player_stats.username
        if parsed is None:
            cleared = await asyncio.to_thread(db.clear_bbastats_name_color, ign)
            if cleared:
                await interaction.followup.send(
                    f"cleared custom color for **{ign}** on `/bbastats`",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"**{ign}** had no saved override (built-in defaults still apply if any)",
                    ephemeral=True,
                )
            return

        await asyncio.to_thread(db.set_bbastats_name_color, ign, parsed)
        await asyncio.to_thread(db.track_player_stats, player_stats.uuid, player_stats.username, player_stats.raw)

        period_key = config.default_period_key()
        period_label = config.period_label(period_key)
        raw_for_card = await asyncio.to_thread(db.get_player_raw, player_stats.uuid, period_key)
        percentiles = await asyncio.to_thread(db.compute_percentiles, player_stats.uuid, period_key)
        tracked_total = await asyncio.to_thread(db.qualified_player_count, period_key)
        min_games = db.min_games_for_ranking(period_key)
        display_username = theme.DISPLAY_NAME_OVERRIDES.get(ign.lower(), ign)

        image = await asyncio.to_thread(
            render_stats_card,
            display_username,
            player_stats.uuid,
            raw_for_card,
            percentiles,
            tracked_total,
            "number",
            period_label,
            min_games,
            None,
            heart_username=ign,
        )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(buffer, filename=f"{ign}_debug_preview.png")
        await interaction.followup.send(
            f"set **{ign}** to `rgb{parsed}` on `/bbastats` only",
            file=file,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DebugCog(bot))
