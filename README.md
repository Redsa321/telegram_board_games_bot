# Telegram Board Games Bot

Public beta Telegram bot for draughts, chess, robot games, and global matchmaking. Current version: `0.1.0-beta.1`.

## Features

- Draughts and chess rendered as Telegram inline keyboards
- Local invites, inline-mode invites, and private global matchmaking
- Rated and unrated modes, Elo ratings, ranks, and kyzma-coins
- Easy, Normal, and Hard robot opponents
- Per-move global timers with pre-game timeout agreement
- Local/global and draughts/chess stats and leaderboards
- Persistent SQLite queues, games, wallets, ratings, and move history
- English, Ukrainian, Russian, and Polish local UI; global games use English

## Local Setup

Python 3.11 or newer is required. Python 3.12 is the release target.

```bash
cp .env.example .env
make setup
```

Set `BOT_TOKEN` in `.env`. Set `ADMIN_USER_ID` to your Telegram numeric user ID and optionally set `FEEDBACK_CHAT_ID`; feedback goes to the admin ID when the latter is empty.

```bash
make           # run the bot
make test      # run tests
make lint      # run Ruff
make backup    # write a checked backup under backups/
```

After the initial setup, use the update script to back up the configured
database, pull the latest code, refresh dependencies, and start the bot:

```bash
./update-and-run.sh
```

Stop an already running bot with `Ctrl+C` before using the update script.

Only one bot process can use a database at a time. A second process exits before polling begins.

For update-safe local storage, put the SQLite file outside the Git checkout and require it to exist:

```dotenv
DATABASE_URL=sqlite:////absolute/path/to/telegram-board-games-bot/bot.db
DATABASE_REQUIRE_EXISTING=true
```

With the guard enabled, a wrong or missing path stops startup instead of creating an empty database. `make backup` automatically uses the database configured in `.env`.

Before opening the beta to testers, rotate the BotFather token, place the new token only in `.env`, and keep that file readable only by the service account.

## Lubuntu 24.04 Hosting

Install host packages and create a dedicated service account:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
sudo useradd --system --home-dir /opt/telegram-board-games-bot --create-home --shell /usr/sbin/nologin telegrambot
sudo git clone <repository-url> /opt/telegram-board-games-bot
sudo chown -R telegrambot:telegrambot /opt/telegram-board-games-bot
sudo -u telegrambot cp /opt/telegram-board-games-bot/.env.example /opt/telegram-board-games-bot/.env
sudo -u telegrambot make -C /opt/telegram-board-games-bot setup
sudo chmod 600 /opt/telegram-board-games-bot/.env
```

Edit `/opt/telegram-board-games-bot/.env`, then install and start the service and daily backup timer:

```bash
sudo cp /opt/telegram-board-games-bot/deploy/*.service /etc/systemd/system/
sudo cp /opt/telegram-board-games-bot/deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-board-games-bot.service
sudo systemctl enable --now telegram-board-games-bot-backup.timer
```

Operational commands:

```bash
systemctl status telegram-board-games-bot
journalctl -u telegram-board-games-bot -f
sudo systemctl start telegram-board-games-bot-backup.service
sudo -u telegrambot /opt/telegram-board-games-bot/.venv/bin/python -m telegram_board_games_bot.backup restore --backup /opt/telegram-board-games-bot/backups/<backup>.db --database /opt/telegram-board-games-bot/bot.db
```

Stop the bot before restoring a backup, then start it again. Backups are made online through SQLite's backup API and the seven newest files are retained.

## Beta Operations

- `/feedback <message>` sends a report to the configured feedback chat. Reply to a board to attach its game ID.
- `/admin_status` is limited to `ADMIN_USER_ID` and reports queue, active game, database, and error counts.
- `/admin_message <text>` is limited to `ADMIN_USER_ID` and broadcasts to every active group known to the bot.
- `/resume_global` recreates a deleted global game message.
- `/cancel_global` leaves the queue, cancels timeout setup, or resigns an active global game.
- `/privacy` describes stored account and game data.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

Performance work is staged in [docs/optimization-plan.md](docs/optimization-plan.md).
