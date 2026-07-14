"""Entrypoint for the Battle Box Arena statistics Discord bot."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import config
from db.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bba-bot")

INTENTS = discord.Intents.default()

COGS = ("cogs.link", "cogs.stats", "cogs.party")


class BbaBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix=commands.when_mentioned, intents=INTENTS)

    async def setup_hook(self) -> None:
        for cog in COGS:
            await self.load_extension(cog)

        if config.DEV_GUILD_ID:
            guild = discord.Object(id=int(config.DEV_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to dev guild %s", len(synced), config.DEV_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d command(s) globally", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")


async def main() -> None:
    if not config.DISCORD_TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Locally: copy .env.example to .env and fill it in. "
            "On a host: set DISCORD_TOKEN in its environment variables / Variables panel."
        )
    if not config.MCC_API_KEY:
        raise SystemExit(
            "MCC_API_KEY is not set. Locally: copy .env.example to .env and fill it in. "
            "On a host: set MCC_API_KEY in its environment variables / Variables panel."
        )

    init_db()

    bot = BbaBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
