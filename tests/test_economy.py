import asyncio
import random
import sqlite3
from datetime import date

from telegram_board_games_bot.db import Database, UpsertChat, UpsertUser
from telegram_board_games_bot.economy import (
    DAILY_CLAIM_KYZMA_COINS,
    STARTER_KYZMA_COINS,
    award_finished_game_currency,
    claim_daily_kyzma_bonus,
    configure_robot_prize,
    kyzma_game_cost_from_values,
    kyzma_value_from_rating,
    roll_prize_multiplier,
    set_kyzma_prize,
)
from telegram_board_games_bot.games.draughts import DraughtsState, GameStatus, PieceColor
from telegram_board_games_bot.games.robot import RobotDifficulty, robot_user_id


class DbGameStub:
    id = "game-1"
    chat_id = 100
    rated = True


def test_kyzma_value_and_game_cost_formula() -> None:
    assert kyzma_value_from_rating(1000) == 50
    assert kyzma_value_from_rating(1400) == 100
    assert kyzma_game_cost_from_values(50, 100) == 15
    assert STARTER_KYZMA_COINS == kyzma_game_cost_from_values(50, 50) * 10


def test_new_stats_start_with_starter_coins(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(100, "group", "group"))
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))

        stats = await database.ensure_user_stats(100, 10, "draughts")

        assert stats.kyzma_coin_balance == STARTER_KYZMA_COINS
        database.close()

    asyncio.run(scenario())


def test_daily_claim_is_once_per_day(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(100, "group", "group"))
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))

        first = await claim_daily_kyzma_bonus(database, 100, 10, "draughts", date(2026, 6, 18))
        second = await claim_daily_kyzma_bonus(database, 100, 10, "draughts", date(2026, 6, 18))
        next_day = await claim_daily_kyzma_bonus(database, 100, 10, "draughts", date(2026, 6, 19))

        assert first.claimed is True
        assert first.amount == DAILY_CLAIM_KYZMA_COINS
        assert first.balance == STARTER_KYZMA_COINS + DAILY_CLAIM_KYZMA_COINS
        assert second.claimed is False
        assert second.balance == first.balance
        assert next_day.claimed is True
        assert next_day.balance == STARTER_KYZMA_COINS + DAILY_CLAIM_KYZMA_COINS * 2
        database.close()

    asyncio.run(scenario())


def test_roll_prize_multiplier_uses_requested_range() -> None:
    multiplier = roll_prize_multiplier(random.Random(1))

    assert 2 <= multiplier <= 20


def test_kyzma_prize_round_trips_in_state() -> None:
    state = DraughtsState.new(10, 20)
    set_kyzma_prize(state, 15, random.Random(1))
    state.accepted_user_ids = [10]

    restored = DraughtsState.from_json(state.to_json())

    assert restored.kyzma_prize_base == 15
    assert restored.kyzma_prize_multiplier is not None
    assert restored.kyzma_prize == 15 * restored.kyzma_prize_multiplier
    assert restored.accepted_user_ids == [10]


def test_configure_robot_prize_uses_difficulty_base() -> None:
    state = DraughtsState.new(robot_user_id(RobotDifficulty.HARD), 20)

    configure_robot_prize(state, "hard")

    assert state.kyzma_prize_base == 20
    assert state.kyzma_prize_multiplier is not None
    assert state.kyzma_prize == 20 * state.kyzma_prize_multiplier


def test_award_finished_game_currency_is_idempotent(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(100, "group", "group"))
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.upsert_user(UpsertUser(20, "bob", "Bob", None, "en"))
        state = DraughtsState.new(10, 20)
        state.status = GameStatus.FINISHED
        state.winner = PieceColor.BLACK
        state.kyzma_prize_base = 10
        state.kyzma_prize_multiplier = 3
        state.kyzma_prize = 30

        first = await award_finished_game_currency(database, DbGameStub(), state, "draughts")
        second = await award_finished_game_currency(database, DbGameStub(), state, "draughts")
        stats = await database.get_user_stats(100, 10, "draughts")

        assert first is True
        assert second is False
        assert stats.kyzma_coin_balance == STARTER_KYZMA_COINS + 30
        database.close()

    asyncio.run(scenario())


def test_charge_entry_fee_debits_both_players_once(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(100, "group", "group"))
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.upsert_user(UpsertUser(20, "bob", "Bob", None, "en"))
        first = await database.charge_kyzma_coins_once("game-1", 100, (10, 20), "draughts", 10, "pvp_entry_fee")
        second = await database.charge_kyzma_coins_once("game-1", 100, (10, 20), "draughts", 10, "pvp_entry_fee")
        alice = await database.get_user_stats(100, 10, "draughts")
        bob = await database.get_user_stats(100, 20, "draughts")

        assert first.success is True
        assert first.already_charged is False
        assert second.success is True
        assert second.already_charged is True
        assert alice.kyzma_coin_balance == STARTER_KYZMA_COINS - 10
        assert bob.kyzma_coin_balance == STARTER_KYZMA_COINS - 10
        database.close()

    asyncio.run(scenario())


def test_charge_entry_fee_rejects_insufficient_balance(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(100, "group", "group"))
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.upsert_user(UpsertUser(20, "bob", "Bob", None, "en"))
        await database.award_kyzma_coins_once("seed-10", 100, 10, "draughts", 25, None, "seed")

        result = await database.charge_kyzma_coins_once("game-1", 100, (10, 20), "draughts", 110, "pvp_entry_fee")
        alice = await database.get_user_stats(100, 10, "draughts")
        bob = await database.get_user_stats(100, 20, "draughts")

        assert result.success is False
        assert result.insufficient_user_ids == (20,)
        assert alice.kyzma_coin_balance == STARTER_KYZMA_COINS + 25
        assert bob is None
        database.close()

    asyncio.run(scenario())


def test_kyzma_event_table_migrates_from_unique_game_id(tmp_path) -> None:
    db_path = tmp_path / "bot.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE users (
            telegram_user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            language_code TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE chats (
            telegram_chat_id INTEGER PRIMARY KEY,
            title TEXT,
            kind TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE kyzma_coin_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL UNIQUE,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            game_kind TEXT NOT NULL,
            amount INTEGER NOT NULL,
            multiplier INTEGER,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO users (telegram_user_id, first_name) VALUES (10, 'Alice'), (20, 'Bob');
        INSERT INTO chats (telegram_chat_id, title, kind) VALUES (100, 'group', 'group');
        INSERT INTO kyzma_coin_events (game_id, chat_id, user_id, game_kind, amount, reason, created_at)
        VALUES ('old-game', 100, 10, 'draughts', 5, 'pvp', 'now');
    """)
    conn.close()

    async def scenario() -> None:
        database = Database.connect(str(db_path))
        await database.run_migrations()
        await database.award_kyzma_coins_once("game-1", 100, 10, "draughts", 25, None, "seed")
        await database.award_kyzma_coins_once("game-1", 100, 20, "draughts", 25, None, "seed")
        database.close()

    asyncio.run(scenario())


def test_legacy_empty_stats_get_one_starter_grant(tmp_path) -> None:
    db_path = tmp_path / "bot.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE users (
            telegram_user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            language_code TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE chats (
            telegram_chat_id INTEGER PRIMARY KEY,
            title TEXT,
            kind TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE chat_user_stats (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            game_kind TEXT NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            draws INTEGER NOT NULL DEFAULT 0,
            rating INTEGER NOT NULL DEFAULT 1000,
            current_streak INTEGER NOT NULL DEFAULT 0,
            best_streak INTEGER NOT NULL DEFAULT 0,
            games_played INTEGER NOT NULL DEFAULT 0,
            kyzma_coin_balance INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(chat_id, user_id, game_kind)
        );
        INSERT INTO users (telegram_user_id, first_name) VALUES (10, 'Alice'), (20, 'Bob');
        INSERT INTO chats (telegram_chat_id, title, kind) VALUES (100, 'group', 'group');
        INSERT INTO chat_user_stats (chat_id, user_id, game_kind, games_played, kyzma_coin_balance)
        VALUES (100, 10, 'draughts', 0, 0), (100, 20, 'draughts', 1, 0);
    """)
    conn.close()

    async def scenario() -> None:
        database = Database.connect(str(db_path))
        await database.run_migrations()
        alice = await database.get_user_stats(100, 10, "draughts")
        bob = await database.get_user_stats(100, 20, "draughts")
        await database.run_migrations()
        alice_again = await database.get_user_stats(100, 10, "draughts")

        assert alice.kyzma_coin_balance == STARTER_KYZMA_COINS
        assert bob.kyzma_coin_balance == 0
        assert alice_again.kyzma_coin_balance == STARTER_KYZMA_COINS
        database.close()

    asyncio.run(scenario())
