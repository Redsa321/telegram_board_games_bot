# Shared PostgreSQL Database

Both Telegram bots use one PostgreSQL database named `kyzma`. Data ownership is separated by schema:

- `shared`: Telegram users, chats, wallets, and the append-only coin ledger.
- `board_games`: games, moves, ratings, queues, views, and board-bot audit events.
- `siski`: growth stats and growth history owned by `telegram_kyzma_siski_bot`.

The board bot owns migrations for `shared` and `board_games`. The siski bot owns Alembic migrations for `siski`. Both may update shared identities and wallets through their repository boundary; neither accesses the other bot's private schema.

Wallet changes are atomic and idempotent. A coin debit and its ledger event happen in one transaction. In the siski bot, the debit, growth result, stats, and history are one PostgreSQL transaction, so the previous cross-database refund window no longer exists.

## Install PostgreSQL on Lubuntu

```bash
sudo apt update
sudo apt install -y postgresql postgresql-client
sudo systemctl enable --now postgresql
sudo -u postgres createuser --pwprompt kyzma
sudo -u postgres createdb --owner=kyzma kyzma
```

Use a strong URL-safe password. Keep PostgreSQL bound to localhost when both bots run on the same host.

## Safe Cutover

Stop both bots and take copies of both SQLite databases before changing `.env`:

```bash
sudo systemctl stop telegram-board-games-bot telegram-board-games-bot-admin
cp /path/to/bot.db /path/to/bot-before-postgres.db
cp /path/to/siski_bot_local.db /path/to/siski-before-postgres.db
```

Update the board bot dependencies, but do not start it yet:

```bash
cd /path/to/telegram_board_games_bot
git pull --ff-only
rm -f .venv/.bot-installed
make setup
```

Import the board database. The importer verifies SQLite integrity, refuses a populated `board_games` schema, merges shared identities, preserves the authoritative wallet balances, and checks every wallet against its imported ledger:

```bash
DATABASE_URL='postgresql://kyzma:PASSWORD@127.0.0.1:5432/kyzma' \
  make migrate-postgres SOURCE=/absolute/path/to/bot.db
```

Set the same database in the board bot `.env`:

```dotenv
DATABASE_URL=postgresql://kyzma:PASSWORD@127.0.0.1:5432/kyzma
```

Prepare the siski schema and optionally import its SQLite data:

```bash
cd /path/to/telegram_kyzma_siski_bot
git pull --ff-only
make install
DATABASE_URL='postgresql+asyncpg://kyzma:PASSWORD@127.0.0.1:5432/kyzma' \
  .venv/bin/alembic upgrade head
PYTHONPATH=src .venv/bin/python scripts/migrate_sqlite_to_postgres.py \
  --source /absolute/path/to/siski_bot_local.db \
  --target-url 'postgresql+asyncpg://kyzma:PASSWORD@127.0.0.1:5432/kyzma' \
  --confirm
```

Set the siski bot `.env`:

```dotenv
DATABASE_URL=postgresql+asyncpg://kyzma:PASSWORD@127.0.0.1:5432/kyzma
ECONOMY_BACKEND=shared_database
```

Start the board bot first, then the siski bot. Keep the SQLite copies until both bots have been exercised and a PostgreSQL backup has completed successfully.

## Verification

```bash
sudo -u postgres psql -d kyzma -c '\dn'
sudo -u postgres psql -d kyzma -c 'SELECT COUNT(*) FROM shared.users;'
sudo -u postgres psql -d kyzma -c 'SELECT COUNT(*) FROM board_games.games;'
sudo -u postgres psql -d kyzma -c 'SELECT COUNT(*) FROM siski.player_chat_stats;'
sudo -u postgres psql -d kyzma -c "
SELECT w.user_id, w.kyzma_coin_balance, COALESCE(SUM(e.amount), 0) AS ledger_balance
FROM shared.global_wallets w
LEFT JOIN shared.kyzma_coin_events e ON e.user_id = w.user_id
GROUP BY w.user_id, w.kyzma_coin_balance
HAVING w.kyzma_coin_balance <> COALESCE(SUM(e.amount), 0);"
```

The final query must return zero rows.

## Backups

`make backup` detects PostgreSQL and writes a custom-format `pg_dump` containing all three schemas. Install `postgresql-client` on any machine running the backup service. Restoring a PostgreSQL dump replaces the whole shared database; stop both bots first.
