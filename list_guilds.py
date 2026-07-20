"""One-off: list every Discord server this bot is in, plus members.

Requires the bot's "Server Members Intent" enabled in the Discord Developer
Portal (Bot tab), or the members request will 403.
"""
from __future__ import annotations

import config
import requests

HEADERS = {"Authorization": f"Bot {config.DISCORD_TOKEN}"}


def get_guilds() -> list[dict]:
    resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return sorted(resp.json(), key=lambda g: g["name"].lower())


def get_members(guild_id: str) -> list[dict]:
    """Paginate through every guild member (1000 per page)."""
    members: list[dict] = []
    after = "0"
    while True:
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/members",
            headers=HEADERS,
            params={"limit": 1000, "after": after},
            timeout=30,
        )
        if resp.status_code == 403:
            raise PermissionError(
                "Missing Server Members Intent. Enable it in the Discord Developer Portal "
                "(Bot -> Privileged Gateway Intents -> Server Members Intent), then retry."
            )
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        members.extend(page)
        if len(page) < 1000:
            break
        after = page[-1]["user"]["id"]
    return members


def member_label(member: dict) -> str:
    user = member["user"]
    name = user.get("global_name") or user.get("username") or "?"
    username = user.get("username", "?")
    bot_tag = " [bot]" if user.get("bot") else ""
    nick = member.get("nick")
    if nick and nick != name:
        return f"{nick} ({username}){bot_tag} - {user['id']}"
    return f"{name} (@{username}){bot_tag} - {user['id']}"


def safe_print(text: str) -> None:
    print(text.encode("ascii", errors="replace").decode("ascii"))


def main() -> None:
    guilds = get_guilds()
    safe_print(f"{len(guilds)} server(s)")
    for g in guilds:
        safe_print("")
        safe_print(f"=== {g['name']} - {g['id']} ===")
        try:
            members = get_members(g["id"])
        except PermissionError as e:
            safe_print(str(e))
            return
        members.sort(key=lambda m: (m["user"].get("username") or "").lower())
        safe_print(f"{len(members)} member(s)")
        for m in members:
            safe_print(f"  {member_label(m)}")


if __name__ == "__main__":
    main()
