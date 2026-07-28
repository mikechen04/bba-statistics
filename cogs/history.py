"""Owner-only DM command for personal BBA match history."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import config


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def render_history_message(payload: dict[str, Any], count: int) -> str:
    matches: list[dict[str, Any]] = payload.get("matches") or []
    if not matches:
        return "No recorded matches yet."

    recent = matches[:count]
    lines: list[str] = []
    total_k = total_a = total_d = total_pts = 0
    total_elo = 0
    elo_seen = 0

    for idx, m in enumerate(recent, start=1):
        k = _as_int(m.get("kills")) or 0
        a = _as_int(m.get("assists")) or 0
        d = _as_int(m.get("deaths")) or 0
        pts = _as_int(m.get("points")) or 0
        elo = _as_int(m.get("eloDelta"))
        mode = (m.get("mode") or "BATTLE_BOX").replace("_", " ").title()
        placement = _as_int(m.get("placement"))
        score = _as_int(m.get("finalScore"))
        ended = str(m.get("endedAt") or "?").replace("T", " ").replace("Z", " UTC")
        ppr = m.get("pointsPerRound") or []
        ppr_txt = ", ".join(str(x) for x in ppr[:12]) if isinstance(ppr, list) and ppr else "-"
        elo_txt = f"{elo:+d}" if elo is not None else "n/a"
        place_txt = f"#{placement}" if placement is not None else "n/a"
        score_txt = str(score) if score is not None else "n/a"
        lines.append(
            f"**{idx}.** `{mode}` | {ended}\n"
            f"K/A/D `{k}/{a}/{d}` | Points `{pts}` | Place `{place_txt}` | Score `{score_txt}` | Elo `{elo_txt}`\n"
            f"Round points: `{ppr_txt}`"
        )
        total_k += k
        total_a += a
        total_d += d
        total_pts += pts
        if elo is not None:
            total_elo += elo
            elo_seen += 1

    summary = (
        f"Totals over last {len(recent)}: "
        f"K/A/D `{total_k}/{total_a}/{total_d}` | Points `{total_pts}` | Elo `{total_elo:+d}`"
        if elo_seen
        else f"Totals over last {len(recent)}: K/A/D `{total_k}/{total_a}/{total_d}` | Points `{total_pts}`"
    )
    body = "\n\n".join(lines)
    msg = f"{summary}\n\n{body}"
    if len(msg) > 1900:
        msg = msg[:1890] + "\n…"
    return msg


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

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            await interaction.response.send_message(f"Failed to read history JSON: `{exc}`", ephemeral=True)
            return

        msg = render_history_message(payload, int(count))
        await interaction.response.send_message(msg, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HistoryCog(bot))
