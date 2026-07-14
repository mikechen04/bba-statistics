# BBA Statistics Bot

A Discord bot for MCC Island **Battle Box Arena** stats.

## Features

- **`/bbastats [username]`** — your (or another player's) BBA stats as an image card, with rank/percentile badges and gold stars on stats that meet "Expert" LFG requirements.
- **`/bbaparty [username]`** — shows who a player is partied up with as an image card, or that they're solo queuing.
- **`/link mc_username`** — link your Discord account to an MC username so you can omit `username` above.
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
