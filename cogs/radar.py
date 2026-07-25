"""/bbaradar: radar-chart profile for one player, or an overlap compare of two."""
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
from render.radar_card import RadarPlayer, render_radar_card

log = logging.getLogger(__name__)


async def _fetch_player(username: str):
    """Fetch + cache one player's stats, or raise a short user-facing string."""
    try:
        player_stats = await asyncio.to_thread(client.get_player_stats, username)
    except PlayerNotFoundError:
        raise UserFacingError("u mispelled their username") from None
    except StatisticsPrivateError:
        raise UserFacingError("their statistics api is off") from None
    except RateLimitedError:
        raise UserFacingError("rate limited :pensive:") from None
    except McApiError as e:
        log.exception("Error fetching player stats for /bbaradar")
        raise UserFacingError(f"uhh {e}") from e

    await asyncio.to_thread(db.upsert_player_stats, player_stats.uuid, player_stats.username, player_stats.raw)
    return player_stats


class RadarCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="bbaradar",
        description="Radar profile for a player, or compare/overlap two players.",
    )
    @app_commands.describe(
        username1="First MCC Island username (defaults to your linked account).",
        username2="Optional second username to overlay on the radar.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def bbaradar(
        self,
        interaction: discord.Interaction,
        username1: str | None = None,
        username2: str | None = None,
    ) -> None:
        await interaction.response.defer()

        try:
            target1 = await resolve_target_username(interaction, username1)
        except UserFacingError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        try:
            p1 = await _fetch_player(target1)
            p2 = await _fetch_player(username2.strip()) if username2 and username2.strip() else None
        except UserFacingError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        if p2 and p1.uuid == p2.uuid:
            await interaction.followup.send("those are the same person lol", ephemeral=True)
            return

        players = [
            RadarPlayer(
                username=p1.username,
                uuid=p1.uuid,
                raw=p1.raw,
                color=theme.MAIN,
            )
        ]
        if p2:
            players.append(
                RadarPlayer(
                    username=p2.username,
                    uuid=p2.uuid,
                    raw=p2.raw,
                    color=theme.ACCENT,
                )
            )

        image = await asyncio.to_thread(render_radar_card, players)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        names = "_vs_".join(p.username for p in players)
        file = discord.File(buffer, filename=f"{names}_bba_radar.png")
        await interaction.followup.send(file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RadarCog(bot))
