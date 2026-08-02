"""Entrypoint for the Battle Box Arena statistics Discord bot."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import discord
import requests
from discord.ext import commands, tasks

import config
import db.database as db
from db.database import init_db
from mcc_api.client import McApiError, client
from mcc_api.queries import LEADERBOARD_SEED_KEYS
from cogs.history import send_history_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bba-bot")

INTENTS = discord.Intents.default()
INTENTS.message_content = True

COGS = ("cogs.link", "cogs.stats", "cogs.party", "cogs.leaderboard", "cogs.radar", "cogs.history")


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
        self.activate_season4.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")

    async def on_message(self, message: discord.Message) -> None:
        # Owner-only, DMs only — no slash command, so other users never see it.
        # DM the bot one of:
        # servers / server / members / guilds
        # history / myhistory [count]
        if message.guild is not None or message.author.bot:
            return

        content = (message.content or "").strip().lower()
        history_trigger = False
        requested_count = 5
        if content:
            parts = content.split()
            head = parts[0]
            if head in {"history", "myhistory", "matchhistory", "matches"}:
                history_trigger = True
                if len(parts) >= 2:
                    try:
                        requested_count = int(parts[1])
                    except Exception:
                        requested_count = 5
                requested_count = max(1, min(10, requested_count))

        if not history_trigger and content not in {"servers", "server", "members", "guilds"}:
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

        if history_trigger:
            path: Path = config.MATCH_HISTORY_PATH
            if not path.exists():
                await message.channel.send(
                    f"No history file found at `{path}`.\nUpload `battlebox-qol-match-history.json` to the bot server first."
                )
                return

            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                await message.channel.send(f"Failed to read history JSON: `{exc}`")
                return

            await send_history_image(message.channel, payload, requested_count)
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
                await asyncio.to_thread(db.track_player_stats, player.uuid, player.username, player.raw)
            log.info("Leaderboard seed: cached %d player(s) from %s", len(players), stat_key)

    @tasks.loop(minutes=1)
    async def activate_season4(self) -> None:
        """Once Season 4 starts, freeze a baseline snapshot for the tracked pool."""
        if not await asyncio.to_thread(db.season_needs_activation, config.SEASON4_KEY):
            return

        total_seeded = 0
        for stat_key in LEADERBOARD_SEED_KEYS:
            try:
                players = await asyncio.to_thread(client.get_leaderboard, stat_key)
            except McApiError:
                log.exception("Season 4 activation seed failed for stat %s", stat_key)
                continue
            total_seeded += len(players)
            for player in players:
                await asyncio.to_thread(db.track_player_stats, player.uuid, player.username, player.raw)

        frozen = await asyncio.to_thread(db.capture_season_baselines_for_all, config.SEASON4_KEY)
        await asyncio.to_thread(db.mark_season_activated, config.SEASON4_KEY)
        log.info(
            "Season 4 activated at %s; seeded %d player rows and froze %d season baselines",
            config.SEASON4_START_AT.isoformat(),
            total_seeded,
            frozen,
        )

    @seed_leaderboards.before_loop
    async def _before_seed_leaderboards(self) -> None:
        await self.wait_until_ready()

    @activate_season4.before_loop
    async def _before_activate_season4(self) -> None:
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
