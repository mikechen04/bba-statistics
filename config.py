"""Centralized configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
FONTS_DIR = BASE_DIR / "render" / "fonts"

DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID") or None

MCC_API_KEY = os.getenv("MCC_API_KEY", "")
CONTACT_INFO = os.getenv("CONTACT_INFO", "unknown")
MCC_API_URL = "https://api.mccisland.net/graphql"
MCC_USER_AGENT = f"bba-statistics-discord-bot (contact: {CONTACT_INFO})"

DB_PATH = DATA_DIR / "bba.sqlite3"

GAME = "BATTLE_BOX_ARENA"
