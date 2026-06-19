# Telegram Board Games Bot

Python rewrite of the Rust Telegram draughts/checkers bot.

## Features

- `/start`, `/help`, `/play_draughts`, `/play_robot`, `/stats`, `/top`, `/resign`
- 8x8 draughts board rendered as Telegram inline keyboard buttons
- Mandatory captures, multi-captures, flying kings, promotion, resignations
- Human vs robot games with Easy, Normal, and Hard difficulty
- Per-chat kyzma-coins economy with player balances, rating-based values, and rolled game prizes
- Inline-mode invites and unrated inline games
- Rated group games with Elo-style stats and leaderboard
- English, Ukrainian, Russian, and Polish UI strings
- SQLite storage compatible with the Rust bot's final schema

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env` and set `BOT_TOKEN`.

## Run

```bash
python -m telegram_board_games_bot
```

By default the bot uses `sqlite:///bot.db`. Override with `DATABASE_URL`.

## Test

```bash
pytest
```
