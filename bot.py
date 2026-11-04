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

COGS = ("cogs.link", "cogs.stats", "cogs.party", "cogs.leaderboard", "cogs.radar", "cogs.history", "cogs.debug")


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
        self.activate_seasons.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")

    async def _sender_is_owner(self, user: discord.abc.User) -> bool:
        if config.OWNER_DISCORD_IDS:
            return user.id in config.OWNER_DISCORD_IDS
        return await self.is_owner(user)

    async def _owner_ids(self) -> set[int]:
        if config.OWNER_DISCORD_IDS:
            return set(config.OWNER_DISCORD_IDS)
        app = self.application
        if app is None:
            await self.application_info()
            app = self.application
        owner = getattr(app, "owner", None) if app else None
        return {owner.id} if owner else set()

    async def _forward_user_dm(self, message: discord.Message, stored_id: int) -> None:
        text = (message.content or "").strip() or "(no text)"
        files = [a.filename for a in message.attachments]
        extra = f"\n[{len(files)} attachment(s): {', '.join(files)}]" if files else ""
        label = message.author.display_name
        uname = message.author.name
        payload = (
            f"**DM from {label} (@{uname})** `{message.author.id}` · #{stored_id}\n"
            f"{text}{extra}"
        )
        for owner_id in await self._owner_ids():
            if owner_id == message.author.id:
                continue
            try:
                owner = await self.fetch_user(owner_id)
                await owner.send(payload[:1900])
            except Exception:
                log.exception("Failed to forward user DM to owner %s", owner_id)

    async def _handle_user_dm(self, message: discord.Message) -> None:
        text = (message.content or "").strip()
        files = [a.filename for a in message.attachments]
        if not text and not files:
            log.warning(
                "Got an empty DM from %s (%s) — enable Message Content Intent if this was text",
                message.author,
                message.author.id,
            )
            return

        stored_id = await asyncio.to_thread(
            db.save_bot_dm,
            str(message.author.id),
            message.author.display_name,
            message.author.name,
            text,
            ", ".join(files),
        )
        log.info("Stored user DM #%s from %s (%s)", stored_id, message.author, message.author.id)
        await self._forward_user_dm(message, stored_id)
        await message.channel.send("got it")

    async def _send_dm_inbox(self, message: discord.Message) -> None:
        rows = await asyncio.to_thread(db.list_bot_dms, 20)
        if not rows:
            await message.channel.send("no user dms yet")
            return
        chunks = [f"**{len(rows)} latest user DM(s)**"]
        for row in rows:
            stamp = (row.get("received_at") or "")[:19].replace("T", " ")
            who = row.get("display_name") or row.get("username") or "?"
            uname = row.get("username") or "?"
            body = (row.get("content") or "").strip() or "(no text)"
            files = (row.get("attachments") or "").strip()
            extra = f"\n[{files}]" if files else ""
            chunks.append(
                f"\n**#{row['id']}** {who} (@{uname}) `{row['discord_id']}` · {stamp}\n{body}{extra}"
            )
        text = "\n".join(chunks)
        while text:
            await message.channel.send(text[:1900])
            text = text[1900:]

    async def on_message(self, message: discord.Message) -> None:
        # DMs only. Owner commands:
        # servers / server / members / guilds
        # history / myhistory [count]
        # inbox / dms / messages
        # Everyone else: store + forward the DM to the owner (VIP color requests, etc).
        if message.guild is not None or message.author.bot:
            return

        content = (message.content or "").strip().lower()
        history_trigger = False
        inbox_trigger = False
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
            elif head in {"inbox", "dms", "messages", "mail"}:
                inbox_trigger = True

        owner_command = history_trigger or inbox_trigger or content in {"servers", "server", "members", "guilds"}
        if not owner_command:
            await self._handle_user_dm(message)
            return

        allowed = await self._sender_is_owner(message.author)
        if not allowed:
            # Treat a non-owner typing an owner keyword as a normal user DM.
            await self._handle_user_dm(message)
            return

        if inbox_trigger:
            await self._send_dm_inbox(message)
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
    async def activate_seasons(self) -> None:
        """Activate any seasonal period whose start time has arrived.

        A period that follows a closed season is frozen from the current DB
        first (so Season 4 stays view-only), then leaderboards are seeded so
        new games land in the new period. A first-of-its-kind season still
        seeds first so the start baseline is as complete as possible.
        """
        periods = sorted(config.STAT_PERIODS.values(), key=lambda p: p.start_at)
        for period in periods:
            if not await asyncio.to_thread(db.season_needs_activation, period.key):
                continue

            previous = config.previous_period(period.key)
            if previous is not None:
                finals, frozen = await asyncio.to_thread(db.freeze_season_end, previous.key, period.key)
                await asyncio.to_thread(db.mark_season_activated, period.key)
                log.info(
                    "%s activated at %s; froze %d %s finals and %d %s baselines",
                    period.label,
                    period.start_at.isoformat(),
                    finals,
                    previous.label,
                    frozen,
                    period.label,
                )
            elif await asyncio.to_thread(db.is_season_ended, period.key):
                # Too late to open this window from live totals — that would
                # freeze today's lifetime as the start and show 0 season stats.
                await asyncio.to_thread(db.mark_season_activated, period.key)
                log.warning(
                    "%s start was missed; marking activated without recapturing baselines",
                    period.label,
                )
                continue
            else:
                total_seeded = 0
                for stat_key in LEADERBOARD_SEED_KEYS:
                    try:
                        players = await asyncio.to_thread(client.get_leaderboard, stat_key)
                    except McApiError:
                        log.exception("%s activation seed failed for stat %s", period.label, stat_key)
                        continue
                    total_seeded += len(players)
                    for player in players:
                        await asyncio.to_thread(db.track_player_stats, player.uuid, player.username, player.raw)

                frozen = await asyncio.to_thread(db.capture_season_baselines_for_all, period.key)
                await asyncio.to_thread(db.mark_season_activated, period.key)
                log.info(
                    "%s activated at %s; seeded %d player rows and froze %d season baselines",
                    period.label,
                    period.start_at.isoformat(),
                    total_seeded,
                    frozen,
                )

            if previous is not None:
                for stat_key in LEADERBOARD_SEED_KEYS:
                    try:
                        players = await asyncio.to_thread(client.get_leaderboard, stat_key)
                    except McApiError:
                        log.exception("%s post-freeze seed failed for stat %s", period.label, stat_key)
                        continue
                    for player in players:
                        await asyncio.to_thread(db.track_player_stats, player.uuid, player.username, player.raw)
                    log.info("%s post-freeze seed: cached %d player(s) from %s", period.label, len(players), stat_key)

    @seed_leaderboards.before_loop
    async def _before_seed_leaderboards(self) -> None:
        await self.wait_until_ready()

    @activate_seasons.before_loop
    async def _before_activate_seasons(self) -> None:
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
