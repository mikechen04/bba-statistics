"""Entrypoint for the Battle Box Arena statistics Discord bot."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands, tasks

import config
import db.database as db
from db.database import init_db
from mcc_api.client import McApiError, client
from mcc_api.queries import LEADERBOARD_SEED_KEYS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bba-bot")

INTENTS = discord.Intents.default()

COGS = ("cogs.link", "cogs.stats", "cogs.party", "cogs.leaderboard")


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

        self.seed_leaderboards.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")

    @tasks.loop(hours=6)
    async def seed_leaderboards(self) -> None:
        """Grows the local percentile pool with real players by crawling the
        handful of BBA stats that expose a public API leaderboard (there's no
        way to enumerate the full MCC Island player base -- see db/database.py).
        """
        for stat_key in LEADERBOARD_SEED_KEYS:
            try:
                players = await asyncio.to_thread(client.get_leaderboard, stat_key)
            except McApiError:
                log.exception("Leaderboard seed failed for stat %s", stat_key)
                continue
            for player in players:
                await asyncio.to_thread(db.upsert_player_stats, player.uuid, player.username, player.raw)
            log.info("Leaderboard seed: cached %d player(s) from %s", len(players), stat_key)

    @seed_leaderboards.before_loop
    async def _before_seed_leaderboards(self) -> None:
        await self.wait_until_ready()


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
