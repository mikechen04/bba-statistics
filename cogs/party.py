"""/bbaparty: shows who a player is currently partied with."""
from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

import db.database as db
from cogs.common import UserFacingError, resolve_target_username
from mcc_api.client import McApiError, PlayerNotFoundError, RateLimitedError, client
from render.party_card import render_party_card

log = logging.getLogger(__name__)


async def _cache_party_members(members: list[dict]) -> None:
    """Opportunistically upserts every party member into the local percentile
    pool, not just whoever ran the command -- this is one of the ways the pool
    grows beyond direct /bbastats lookups (see db/database.py docs). Runs in
    the background after the response is sent, so it never delays the reply.
    Players with private statistics are silently skipped.
    """
    for member in members:
        username = member.get("username")
        if not username:
            continue
        try:
            stats = await asyncio.to_thread(client.get_player_stats, username)
        except McApiError:
            continue
        await asyncio.to_thread(db.upsert_player_stats, stats.uuid, stats.username, stats.raw)


class PartyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="bbaparty", description="Show who a player is currently in a party with.")
    @app_commands.describe(username="MCC Island username to look up (defaults to your linked account).")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def bbaparty(self, interaction: discord.Interaction, username: str | None = None) -> None:
        await interaction.response.defer()

        try:
            target = await resolve_target_username(interaction, username)
        except UserFacingError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        try:
            party_info = await asyncio.to_thread(client.get_player_party, target)
        except PlayerNotFoundError:
            await interaction.followup.send("u mispelled their username", ephemeral=True)
            return
        except RateLimitedError:
            await interaction.followup.send("rate limited :pensive:", ephemeral=True)
            return
        except McApiError as e:
            log.exception("Error fetching player party")
            await interaction.followup.send(f"uhh {e}", ephemeral=True)
            return

        if not party_info.social_enabled:
            await interaction.followup.send("their social api is off", ephemeral=True)
            return

        if not party_info.active:
            await interaction.followup.send("user is solo queuing")
            return

        members = list(party_info.members)
        if party_info.leader and not any(m["uuid"] == party_info.leader["uuid"] for m in members):
            members = [party_info.leader, *members]

        if not members:
            await interaction.followup.send("user is solo queuing")
            return

        image = await asyncio.to_thread(render_party_card, party_info.leader, members)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(buffer, filename=f"{party_info.username}_bba_party.png")
        await interaction.followup.send(file=file)

        asyncio.create_task(_cache_party_members(members))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PartyCog(bot))
