"""Shared helpers used by multiple slash command cogs."""
from __future__ import annotations

import discord
from discord import app_commands

import config
import db.database as db


class UserFacingError(Exception):
    """An error whose message is safe to show directly to the Discord user."""


PERIOD_CHOICES = [
    app_commands.Choice(name=name, value=value) for name, value in config.period_choice_values()
]


def resolve_period(period: app_commands.Choice[str] | None) -> tuple[str, str]:
    key = period.value if period else config.default_period_key()
    return key, config.period_label(key)


async def resolve_target_username(interaction: discord.Interaction, username: str | None) -> str:
    """Resolve which Minecraft username a command should look up.

    Priority: an explicit `username` option, otherwise the invoking Discord
    user's linked account (see /link).
    """
    if username:
        return username.strip()

    linked = db.get_linked_account(str(interaction.user.id))
    if linked:
        return linked[1]

    raise UserFacingError(
        "u forgot to give a username or u dont have it linked dumb fuck\n"
        "`/bbastats username (mc username)` or `/link (username)`"
    )
