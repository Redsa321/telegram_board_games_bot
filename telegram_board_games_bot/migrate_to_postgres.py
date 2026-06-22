from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from .db import Database, is_postgres_url

PRIVATE_TABLES = (
    "games",
    "moves",
    "chat_user_stats",
    "global_user_stats",
    "matchmaking_queue",
    "game_views",
    "head_to_head_stats",
    "audit_events",
    "inline_invites",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import the board bot SQLite database into PostgreSQL.")
    parser.add_argument("--source", type=Path, required=True, help="Existing SQLite bot.db")
    parser.add_argument("--target-url", help="PostgreSQL URL; defaults to DATABASE_URL")
    parser.add_argument("--confirm", action="store_true", help="Required confirmation for the write")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    target_url = args.target_url or os.getenv("DATABASE_URL", "")
    if not args.confirm:
        raise RuntimeError("migration not started: pass --confirm after taking a backup")
    migrate_sqlite_to_postgres(args.source, target_url)


def migrate_sqlite_to_postgres(source_path: Path, target_url: str) -> None:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if not is_postgres_url(target_url):
        raise ValueError("target must be a postgresql:// URL")

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = Database.connect(target_url)
    try:
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"source database integrity check failed: {integrity}")
        target._run_migrations()
        assert_private_schema_empty(target)
        with target.conn:
            merge_users(source, target)
            merge_chats(source, target)
            ensure_global_chat(target)
            merge_wallets(source, target)
            for table in PRIVATE_TABLES:
                copy_table(source, target, table)
            copy_coin_events(source, target)
            create_opening_ledger_entries(target)
            reset_sequences(target)
        verify_migration(source, target)
    finally:
        source.close()
        target.close()


def assert_private_schema_empty(target: Database) -> None:
    populated = [
        table
        for table in PRIVATE_TABLES
        if int(target.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) > 0
    ]
    if populated:
        raise RuntimeError(f"target board_games schema is not empty: {', '.join(populated)}")
    if int(target.conn.execute("SELECT COUNT(*) FROM chat_registry").fetchone()[0]) > 0:
        raise RuntimeError("target board_games chat registry is not empty")


def merge_users(source: sqlite3.Connection, target: Database) -> None:
    if not table_exists(source, "users"):
        return
    for row in source.execute("SELECT * FROM users"):
        target.conn.execute(
            """
            INSERT INTO users (
                telegram_user_id, username, first_name, last_name, language_code, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name),
                last_name = COALESCE(excluded.last_name, users.last_name),
                language_code = COALESCE(excluded.language_code, users.language_code),
                updated_at = GREATEST(users.updated_at, excluded.updated_at)
            """,
            (
                row["telegram_user_id"],
                row["username"],
                row["first_name"],
                row["last_name"],
                row["language_code"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def merge_chats(source: sqlite3.Connection, target: Database) -> None:
    if not table_exists(source, "chats"):
        return
    for row in source.execute("SELECT * FROM chats"):
        target.conn.execute(
            """
            INSERT INTO chats (
                telegram_chat_id, title, kind, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET
                title = COALESCE(excluded.title, chats.title),
                kind = COALESCE(excluded.kind, chats.kind),
                is_active = excluded.is_active,
                updated_at = GREATEST(chats.updated_at, excluded.updated_at)
            """,
            (
                row["telegram_chat_id"],
                row["title"],
                row["kind"],
                row["is_active"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        target.conn.execute(
            """
            INSERT INTO chat_registry (chat_id, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (row["telegram_chat_id"], row["is_active"], row["created_at"], row["updated_at"]),
        )


def ensure_global_chat(target: Database) -> None:
    now = datetime.now(UTC).isoformat()
    target.conn.execute(
        """
        INSERT INTO chats (telegram_chat_id, title, kind, is_active, created_at, updated_at)
        VALUES (0, 'Global matchmaking', 'private', 1, ?, ?)
        ON CONFLICT(telegram_chat_id) DO NOTHING
        """,
        (now, now),
    )


def merge_wallets(source: sqlite3.Connection, target: Database) -> None:
    if not table_exists(source, "global_wallets"):
        return
    for row in source.execute("SELECT user_id, kyzma_coin_balance, created_at, updated_at FROM global_wallets"):
        target.conn.execute(
            """
            INSERT INTO global_wallets (user_id, kyzma_coin_balance, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                kyzma_coin_balance = excluded.kyzma_coin_balance,
                updated_at = excluded.updated_at
            """,
            tuple(row),
        )


def copy_table(source: sqlite3.Connection, target: Database, table: str) -> None:
    if not table_exists(source, table):
        return
    columns = table_columns(source, table)
    if not columns:
        return
    column_list = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    for row in source.execute(f"SELECT {column_list} FROM {table}"):
        target.conn.execute(
            f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})",
            tuple(row),
        )


def copy_coin_events(source: sqlite3.Connection, target: Database) -> None:
    if not table_exists(source, "kyzma_coin_events"):
        return
    columns = [column for column in table_columns(source, "kyzma_coin_events") if column != "id"]
    column_list = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    for row in source.execute(f"SELECT {column_list} FROM kyzma_coin_events ORDER BY id"):
        target.conn.execute(
            f"""
            INSERT INTO kyzma_coin_events ({column_list}, source_bot)
            VALUES ({placeholders}, 'board_games')
            ON CONFLICT(game_id, user_id, reason) DO NOTHING
            """,
            tuple(row),
        )


def create_opening_ledger_entries(target: Database) -> None:
    now = datetime.now(UTC).isoformat()
    rows = target.conn.execute(
        """
        SELECT
            w.user_id,
            w.kyzma_coin_balance - COALESCE(SUM(e.amount), 0) AS opening_amount
        FROM global_wallets w
        LEFT JOIN kyzma_coin_events e ON e.user_id = w.user_id
        GROUP BY w.user_id, w.kyzma_coin_balance
        """
    ).fetchall()
    for row in rows:
        opening_amount = int(row["opening_amount"])
        if opening_amount == 0:
            continue
        target.conn.execute(
            """
            INSERT INTO kyzma_coin_events (
                game_id, chat_id, user_id, game_kind, amount, multiplier,
                reason, source_bot, details_json, created_at
            ) VALUES (?, 0, ?, 'economy', ?, NULL, 'migration_opening_balance',
                      'board_games', '{"source":"sqlite"}', ?)
            ON CONFLICT(game_id, user_id, reason) DO NOTHING
            """,
            (f"migration-opening:{row['user_id']}", row["user_id"], opening_amount, now),
        )


def reset_sequences(target: Database) -> None:
    for table in ("moves", "audit_events"):
        target.conn.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence('board_games.{table}', 'id'),
                COALESCE(MAX(id), 1),
                MAX(id) IS NOT NULL
            ) FROM {table}
            """
        ).fetchone()


def verify_migration(source: sqlite3.Connection, target: Database) -> None:
    for table in PRIVATE_TABLES:
        source_count = count_rows(source, table)
        target_count = int(target.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        if source_count != target_count:
            raise RuntimeError(f"row-count mismatch for {table}: SQLite={source_count}, PostgreSQL={target_count}")
    source_chat_count = count_rows(source, "chats")
    target_chat_count = int(target.conn.execute("SELECT COUNT(*) FROM chat_registry").fetchone()[0])
    if source_chat_count != target_chat_count:
        raise RuntimeError(
            f"row-count mismatch for chat registry: SQLite={source_chat_count}, PostgreSQL={target_chat_count}"
        )
    mismatch = target.conn.execute(
        """
        SELECT w.user_id
        FROM global_wallets w
        LEFT JOIN kyzma_coin_events e ON e.user_id = w.user_id
        GROUP BY w.user_id, w.kyzma_coin_balance
        HAVING w.kyzma_coin_balance <> COALESCE(SUM(e.amount), 0)
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise RuntimeError(f"wallet ledger mismatch for user {mismatch['user_id']}")


def count_rows(connection: sqlite3.Connection, table: str) -> int:
    if not table_exists(connection, table):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")]


if __name__ == "__main__":
    main()
