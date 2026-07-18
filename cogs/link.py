"""/link and /unlink: map a Discord user to their MCC Island username."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import db.database as db
from mcc_api.client import McApiError, PlayerNotFoundError, RateLimitedError, client

log = logging.getLogger(__name__)


class LinkCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="link", description="Link your Discord account to your MCC Island username.")
    @app_commands.describe(username="Your Minecraft username on MCC Island.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def link(self, interaction: discord.Interaction, username: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            uuid, canonical_username = await asyncio.to_thread(client.resolve_username, username)
        except PlayerNotFoundError:
            await interaction.followup.send("u mispelled their username", ephemeral=True)
            return
        except RateLimitedError:
            await interaction.followup.send("rate limited :pensive:", ephemeral=True)
            return
        except McApiError as e:
            log.exception("Error resolving username for /link")
            await interaction.followup.send(f"uhh {e}", ephemeral=True)
            return

        db.link_account(str(interaction.user.id), uuid, canonical_username)
        await interaction.followup.send(f"linked as **{canonical_username}**!", ephemeral=True)

    @app_commands.command(name="unlink", description="Remove your linked MCC Island username.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def unlink(self, interaction: discord.Interaction) -> None:
        removed = db.unlink_account(str(interaction.user.id))
        message = "bye :(" if removed else "you didnt even link in the first place"
        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LinkCog(bot))
