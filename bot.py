"""Entrypoint for the Battle Box Arena statistics Discord bot."""
from __future__ import annotations

import asyncio
import logging

import discord
import requests
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

    async def on_message(self, message: discord.Message) -> None:
        # Owner-only, DMs only — no slash command, so other users never see it.
        # DM the bot one of: servers / server / members / guilds
        if message.guild is not None or message.author.bot:
            return

        content = (message.content or "").strip().lower()
        if content not in {"servers", "server", "members", "guilds"}:
            if not content:
                log.warning(
                    "Got an empty DM from %s (%s) — enable Message Content Intent if this was 'servers'",
                    message.author,
                    message.author.id,
                )
            return

        allowed = False
        if config.OWNER_DISCORD_IDS:
            allowed = message.author.id in config.OWNER_DISCORD_IDS
        else:
            allowed = await self.is_owner(message.author)

        if not allowed:
            log.info(
                "Ignored servers DM from %s (%s) — not owner. Set OWNER_DISCORD_ID in .env to your user id.",
                message.author,
                message.author.id,
            )
            return

        log.info("servers DM from owner %s (%s)", message.author, message.author.id)
        await message.channel.send("checking...")

        headers = {"Authorization": f"Bot {config.DISCORD_TOKEN}"}

        def _fetch() -> str:
            guilds_resp = requests.get(
                "https://discord.com/api/v10/users/@me/guilds", headers=headers, timeout=15
            )
            guilds_resp.raise_for_status()
            guilds = sorted(guilds_resp.json(), key=lambda g: g["name"].lower())
            if not guilds:
                return "0 servers"

            chunks: list[str] = [f"**{len(guilds)} server(s)**"]
            for g in guilds:
                chunks.append(f"\n**{g['name']}** (`{g['id']}`)")
                members_resp = requests.get(
                    f"https://discord.com/api/v10/guilds/{g['id']}/members",
                    headers=headers,
                    params={"limit": 1000},
                    timeout=30,
                )
                if members_resp.status_code == 403:
                    chunks.append("_can't list members — enable Server Members Intent in the Dev Portal_")
                    continue
                members_resp.raise_for_status()
                members = members_resp.json()
                members.sort(key=lambda m: (m["user"].get("username") or "").lower())
                chunks.append(f"{len(members)} member(s)")
                for m in members:
                    user = m["user"]
                    label = user.get("global_name") or user.get("username") or "?"
                    uname = user.get("username", "?")
                    bot_tag = " [bot]" if user.get("bot") else ""
                    chunks.append(f"- {label} (@{uname}){bot_tag}")
            return "\n".join(chunks)

        try:
            text = await asyncio.to_thread(_fetch)
        except Exception as e:
            await message.channel.send(f"uhh {e}")
            return

        while text:
            await message.channel.send(text[:1900])
            text = text[1900:]

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
