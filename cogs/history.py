"""Owner-only DM command for personal BBA match history."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import config
from render.history_card import render_history_card


def _history_png(payload: dict[str, Any], count: int) -> discord.File:
    image = render_history_card(payload, count)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename="match_history.png")


async def send_history_image(destination, payload: dict[str, Any], count: int) -> None:
    """Render and send the history card to a channel / interaction followup target."""
    file = await asyncio.to_thread(_history_png, payload, count)
    await destination.send(file=file)


class HistoryCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="myhistory", description="Owner-only: show your recent recorded BBA matches.")
    @app_commands.describe(count="How many recent matches to show (1-10).")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=True)
    async def myhistory(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 10] = 5) -> None:
        if interaction.guild is not None:
            await interaction.response.send_message("DM-only command.", ephemeral=True)
            return

        if config.OWNER_DISCORD_IDS and interaction.user.id not in config.OWNER_DISCORD_IDS:
            await interaction.response.send_message("Not allowed.", ephemeral=True)
            return

        path: Path = config.MATCH_HISTORY_PATH
        if not path.exists():
            await interaction.response.send_message(
                f"No history file found at `{path}`.\nUpload `battlebox-qol-match-history.json` from your game PC first.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            await interaction.followup.send(f"Failed to read history JSON: `{exc}`")
            return

        file = await asyncio.to_thread(_history_png, payload, int(count))
        await interaction.followup.send(file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HistoryCog(bot))
