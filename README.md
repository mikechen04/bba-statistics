# BBA Statistics Bot

A Discord bot for MCC Island **Battle Box Arena** stats.

## Features

- **`/bbastats [username] [display]`** — your (or another player's) BBA stats as an image card, with hours played, rank/percentile badges, and gold stars on stats that meet "Expert" LFG requirements.
- **`/bbalb stat`** — top 10 tracked players for a specific BBA stat (kills, WLR, coins per game, etc.). If you're linked and outside the top 10, your own rank is shown at the bottom.
- **`/bbaparty [username]`** — shows who a player is partied up with as an image card, or that they're solo queuing.
- **`/link username`** — link your Discord account to an MC username so you can omit `username` above.
- **`/unlink`** — remove your linked account.

## How to run

1. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN` and `MCC_API_KEY` (and optionally `CONTACT_INFO`, `DEV_GUILD_ID`).

3. Run it:

   ```
   python bot.py
   ```
