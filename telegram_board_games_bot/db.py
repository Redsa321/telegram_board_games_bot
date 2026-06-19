from __future__ import annotations

import json
import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .economy import STARTER_KYZMA_COINS, kyzma_game_cost_from_values, kyzma_value_from_rating


def now_text() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class UpsertUser:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None


@dataclass
class UpsertChat:
    telegram_chat_id: int
    title: str | None
    kind: str | None


@dataclass
class DbUser:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    created_at: str
    updated_at: str


@dataclass
class DbGame:
    id: str
    chat_id: int
    message_id: int | None
    inline_message_id: str | None
    game_kind: str
    status: str
    rated: bool
    state: dict[str, Any]
    current_turn_user_id: int | None
    black_user_id: int
    white_user_id: int
    winner_user_id: int | None
    result_reason: str | None
    created_at: str
    updated_at: str
    finished_at: str | None


@dataclass
class DbMove:
    id: int
    game_id: str
    move_number: int
    user_id: int
    move_text: str
    state_after: dict[str, Any]
    created_at: str


@dataclass
class ChatUserStats:
    chat_id: int
    user_id: int
    game_kind: str
    wins: int
    losses: int
    draws: int
    rating: int
    current_streak: int
    best_streak: int
    games_played: int
    kyzma_coin_balance: int = 0
    starter_kyzma_granted: int = 0


@dataclass
class LeaderboardEntry(ChatUserStats):
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@dataclass
class InlineInvite:
    inline_message_id: str
    challenger_id: int


@dataclass
class NewGame:
    chat_id: int
    message_id: int | None
    inline_message_id: str | None
    game_kind: str
    status: str
    rated: bool
    state: Any
    current_turn_user_id: int | None
    black_user_id: int
    white_user_id: int


@dataclass
class GameStateUpdate:
    game_id: str
    message_id: int | None
    status: str
    state: Any
    current_turn_user_id: int | None


@dataclass
class FinishGame:
    game_id: str
    winner_user_id: int | None
    result_reason: str | None


@dataclass
class NewMove:
    game_id: str
    move_number: int
    user_id: int
    move_text: str
    state_after: Any


@dataclass
class GameOutcome:
    chat_id: int
    game_kind: str
    black_user_id: int
    white_user_id: int
    winner_user_id: int | None


@dataclass(frozen=True)
class KyzmaChargeResult:
    success: bool
    insufficient_user_ids: tuple[int, ...] = ()
    already_charged: bool = False


class _InsufficientKyzmaBalance(Exception):
    def __init__(self, user_ids: tuple[int, ...]):
        super().__init__("insufficient kyzma-coins")
        self.user_ids = user_ids


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    @classmethod
    def connect(cls, database_url: str) -> "Database":
        return cls(database_path(database_url))

    async def run_migrations(self) -> None:
        self._run_migrations()

    def _run_migrations(self) -> None:
        self._maybe_migrate_early_games_table()
        self.conn.executescript(SCHEMA_SQL)
        self._add_column_if_missing("users", "language_code", "TEXT")
        self._add_column_if_missing("games", "inline_message_id", "TEXT")
        self._add_column_if_missing("chat_user_stats", "kyzma_coin_balance", "INTEGER NOT NULL DEFAULT 0")
        self._add_column_if_missing("chat_user_stats", "starter_kyzma_granted", "INTEGER NOT NULL DEFAULT 0")
        self._grant_starter_kyzma_to_legacy_empty_stats()
        self._maybe_migrate_kyzma_coin_events_table()
        self.conn.executescript(INDEX_SQL)
        self.conn.commit()

    def _maybe_migrate_early_games_table(self) -> None:
        if not self._table_exists("games"):
            return
        columns = self._columns("games")
        if "kind" not in columns or "game_kind" in columns:
            return
        self.conn.executescript(EARLY_GAMES_MIGRATION_SQL)

    def _add_column_if_missing(self, table: str, name: str, definition: str) -> None:
        if self._table_exists(table) and name not in self._columns(table):
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _table_exists(self, table: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _columns(self, table: str) -> set[str]:
        return {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def _index_columns(self, index_name: str) -> list[str]:
        return [row["name"] for row in self.conn.execute(f"PRAGMA index_info({index_name})")]

    def _maybe_migrate_kyzma_coin_events_table(self) -> None:
        if not self._table_exists("kyzma_coin_events"):
            return
        has_unique_game_id = any(
            bool(row["unique"]) and self._index_columns(row["name"]) == ["game_id"]
            for row in self.conn.execute("PRAGMA index_list(kyzma_coin_events)")
        )
        if not has_unique_game_id:
            return
        self.conn.executescript(KYZMA_COIN_EVENTS_UNIQUE_GAME_ID_MIGRATION_SQL)

    def _grant_starter_kyzma_to_legacy_empty_stats(self) -> None:
        if not self._table_exists("chat_user_stats") or "starter_kyzma_granted" not in self._columns("chat_user_stats"):
            return
        self.conn.execute(
            """
            UPDATE chat_user_stats
            SET kyzma_coin_balance = kyzma_coin_balance + ?,
                starter_kyzma_granted = 1
            WHERE starter_kyzma_granted = 0
                AND games_played = 0
                AND kyzma_coin_balance = 0
            """,
            (STARTER_KYZMA_COINS,),
        )
        self.conn.execute(
            """
            UPDATE chat_user_stats
            SET starter_kyzma_granted = 1
            WHERE starter_kyzma_granted = 0
            """,
        )

    def _insert_user_stats_ignore(self, chat_id: int, user_id: int, game_kind: str) -> bool:
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO chat_user_stats (
                chat_id, user_id, game_kind, kyzma_coin_balance, starter_kyzma_granted
            )
            VALUES (?, ?, ?, ?, 1)
            """,
            (chat_id, user_id, game_kind, STARTER_KYZMA_COINS),
        )
        return cursor.rowcount == 1

    async def upsert_user(self, user: UpsertUser) -> DbUser:
        now = now_text()
        self.conn.execute(
            """
            INSERT INTO users (
                telegram_user_id, username, first_name, last_name, language_code,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                language_code = excluded.language_code,
                updated_at = excluded.updated_at
            """,
            (user.telegram_user_id, user.username, user.first_name, user.last_name, user.language_code, now, now),
        )
        self.conn.commit()
        return await self.get_user(user.telegram_user_id)

    async def upsert_chat(self, chat: UpsertChat) -> None:
        now = now_text()
        self.conn.execute(
            """
            INSERT INTO chats (telegram_chat_id, title, kind, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET
                title = excluded.title,
                kind = excluded.kind,
                updated_at = excluded.updated_at
            """,
            (chat.telegram_chat_id, chat.title, chat.kind, now, now),
        )
        self.conn.commit()

    async def create_game(self, game: NewGame) -> DbGame:
        game_id = str(uuid.uuid4())
        now = now_text()
        self.conn.execute(
            """
            INSERT INTO games (
                id, chat_id, message_id, inline_message_id, game_kind, status, rated, state_json,
                current_turn_user_id, black_user_id, white_user_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                game.chat_id,
                game.message_id,
                game.inline_message_id,
                game.game_kind,
                game.status,
                int(game.rated),
                dump_state(game.state),
                game.current_turn_user_id,
                game.black_user_id,
                game.white_user_id,
                now,
                now,
            ),
        )
        self.conn.commit()
        db_game = await self.get_game(game_id)
        if db_game is None:
            raise RuntimeError(f"created game {game_id} was not found")
        return db_game

    async def get_game(self, game_id: str) -> DbGame | None:
        row = self.conn.execute(GAME_SELECT + " WHERE id = ?", (game_id,)).fetchone()
        return row_to_game(row) if row else None

    async def update_game_state(self, update: GameStateUpdate) -> None:
        self.conn.execute(
            """
            UPDATE games
            SET status = ?,
                state_json = ?,
                current_turn_user_id = ?,
                message_id = COALESCE(?, message_id),
                updated_at = ?
            WHERE id = ?
            """,
            (
                update.status,
                dump_state(update.state),
                update.current_turn_user_id,
                update.message_id,
                now_text(),
                update.game_id,
            ),
        )
        self.conn.commit()

    async def finish_game(self, finish: FinishGame) -> None:
        now = now_text()
        self.conn.execute(
            """
            UPDATE games
            SET status = 'finished',
                winner_user_id = ?,
                result_reason = ?,
                updated_at = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (finish.winner_user_id, finish.result_reason, now, now, finish.game_id),
        )
        self.conn.commit()

    async def insert_move(self, move: NewMove) -> DbMove:
        now = now_text()
        cursor = self.conn.execute(
            """
            INSERT INTO moves (game_id, move_number, user_id, move_text, state_after_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (move.game_id, move.move_number, move.user_id, move.move_text, dump_state(move.state_after), now),
        )
        self.conn.commit()
        db_move = await self.get_move(cursor.lastrowid)
        if db_move is None:
            raise RuntimeError(f"created move {cursor.lastrowid} was not found")
        return db_move

    async def get_move(self, move_id: int) -> DbMove | None:
        row = self.conn.execute(
            """
            SELECT id, game_id, move_number, user_id, move_text, state_after_json, created_at
            FROM moves WHERE id = ?
            """,
            (move_id,),
        ).fetchone()
        return row_to_move(row) if row else None

    async def get_active_game_by_message(self, chat_id: int, message_id: int) -> DbGame | None:
        row = self.conn.execute(
            GAME_SELECT
            + """
            WHERE chat_id = ? AND message_id = ?
                AND finished_at IS NULL AND status != 'finished'
            ORDER BY created_at DESC LIMIT 1
            """,
            (chat_id, message_id),
        ).fetchone()
        return row_to_game(row) if row else None

    async def get_active_game_by_inline_message(self, inline_message_id: str) -> DbGame | None:
        row = self.conn.execute(
            GAME_SELECT
            + """
            WHERE inline_message_id = ?
                AND finished_at IS NULL AND status != 'finished'
            ORDER BY created_at DESC LIMIT 1
            """,
            (inline_message_id,),
        ).fetchone()
        return row_to_game(row) if row else None

    async def create_inline_invite(self, inline_message_id: str, challenger_id: int) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO inline_invites (inline_message_id, challenger_id, created_at)
            VALUES (?, ?, ?)
            """,
            (inline_message_id, challenger_id, now_text()),
        )
        self.conn.commit()

    async def get_and_delete_inline_invite(self, inline_message_id: str) -> InlineInvite | None:
        with self.conn:
            row = self.conn.execute(
                "SELECT inline_message_id, challenger_id FROM inline_invites WHERE inline_message_id = ?",
                (inline_message_id,),
            ).fetchone()
            if row is None:
                return None
            deleted = self.conn.execute(
                "DELETE FROM inline_invites WHERE inline_message_id = ?",
                (inline_message_id,),
            ).rowcount
            if deleted == 0:
                return None
            return InlineInvite(row["inline_message_id"], row["challenger_id"])

    async def get_group_leaderboard(self, chat_id: int, game_kind: str, limit: int) -> list[LeaderboardEntry]:
        rows = self.conn.execute(
            """
            SELECT
                s.chat_id, s.user_id, s.game_kind, s.wins, s.losses, s.draws,
                s.rating, s.current_streak, s.best_streak, s.games_played,
                s.kyzma_coin_balance,
                u.username, u.first_name, u.last_name
            FROM chat_user_stats s
            LEFT JOIN users u ON u.telegram_user_id = s.user_id
            WHERE s.chat_id = ? AND s.game_kind = ?
            ORDER BY s.rating DESC, s.wins DESC, s.games_played ASC, s.user_id ASC
            LIMIT ?
            """,
            (chat_id, game_kind, limit),
        ).fetchall()
        return [LeaderboardEntry(**dict(row)) for row in rows]

    async def get_user_stats(self, chat_id: int, user_id: int, game_kind: str) -> ChatUserStats | None:
        row = self.conn.execute(
            """
            SELECT chat_id, user_id, game_kind, wins, losses, draws, rating,
                current_streak, best_streak, games_played, kyzma_coin_balance
            FROM chat_user_stats
            WHERE chat_id = ? AND user_id = ? AND game_kind = ?
            """,
            (chat_id, user_id, game_kind),
        ).fetchone()
        return ChatUserStats(**dict(row)) if row else None

    async def update_stats_after_game(self, outcome: GameOutcome) -> None:
        head_user_a, head_user_b = ordered_pair(outcome.black_user_id, outcome.white_user_id)
        user_a_won = outcome.winner_user_id == head_user_a
        user_b_won = outcome.winner_user_id == head_user_b
        draw = outcome.winner_user_id is None
        with self.conn:
            for user_id in (outcome.black_user_id, outcome.white_user_id):
                self._insert_user_stats_ignore(outcome.chat_id, user_id, outcome.game_kind)
            black_stats = await self.get_user_stats(outcome.chat_id, outcome.black_user_id, outcome.game_kind)
            white_stats = await self.get_user_stats(outcome.chat_id, outcome.white_user_id, outcome.game_kind)
            if black_stats is None or white_stats is None:
                raise RuntimeError("stats rows were not created")
            black_score = 1.0 if outcome.winner_user_id == outcome.black_user_id else 0.0 if outcome.winner_user_id else 0.5
            white_score = 1.0 - black_score
            self._apply_stats_result(black_stats, elo_rating(black_stats.rating, white_stats.rating, black_score), outcome.winner_user_id)
            self._apply_stats_result(white_stats, elo_rating(white_stats.rating, black_stats.rating, white_score), outcome.winner_user_id)
            self.conn.execute(
                """
                INSERT INTO head_to_head_stats (
                    chat_id, user_a_id, user_b_id, game_kind, user_a_wins, user_b_wins, draws
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_a_id, user_b_id, game_kind) DO UPDATE SET
                    user_a_wins = user_a_wins + excluded.user_a_wins,
                    user_b_wins = user_b_wins + excluded.user_b_wins,
                    draws = draws + excluded.draws
                """,
                (outcome.chat_id, head_user_a, head_user_b, outcome.game_kind, int(user_a_won), int(user_b_won), int(draw)),
            )

    async def ensure_user_stats(self, chat_id: int, user_id: int, game_kind: str) -> ChatUserStats:
        self._insert_user_stats_ignore(chat_id, user_id, game_kind)
        self.conn.commit()
        stats = await self.get_user_stats(chat_id, user_id, game_kind)
        if stats is None:
            raise RuntimeError("stats row was not created")
        return stats

    async def get_kyzma_value(self, chat_id: int, user_id: int, game_kind: str) -> int:
        stats = await self.get_user_stats(chat_id, user_id, game_kind)
        rating = stats.rating if stats else 1000
        return kyzma_value_from_rating(rating)

    async def get_kyzma_game_cost(self, chat_id: int, left_user_id: int, right_user_id: int, game_kind: str) -> int:
        left_value = await self.get_kyzma_value(chat_id, left_user_id, game_kind)
        right_value = await self.get_kyzma_value(chat_id, right_user_id, game_kind)
        return kyzma_game_cost_from_values(left_value, right_value)

    async def get_kyzma_balances(self, chat_id: int, user_ids: list[int] | tuple[int, ...], game_kind: str) -> dict[int, int]:
        distinct_user_ids = tuple(dict.fromkeys(user_ids))
        if not distinct_user_ids:
            return {}
        should_commit = not self.conn.in_transaction
        for user_id in distinct_user_ids:
            self._insert_user_stats_ignore(chat_id, user_id, game_kind)
        if should_commit:
            self.conn.commit()
        placeholders = ",".join("?" for _ in distinct_user_ids)
        rows = self.conn.execute(
            f"""
            SELECT user_id, kyzma_coin_balance
            FROM chat_user_stats
            WHERE chat_id = ? AND game_kind = ? AND user_id IN ({placeholders})
            """,
            (chat_id, game_kind, *distinct_user_ids),
        ).fetchall()
        balances = {int(row["user_id"]): int(row["kyzma_coin_balance"]) for row in rows}
        return {user_id: balances.get(user_id, 0) for user_id in distinct_user_ids}

    async def get_insufficient_kyzma_user_ids(
        self,
        chat_id: int,
        user_ids: list[int] | tuple[int, ...],
        game_kind: str,
        amount: int,
    ) -> tuple[int, ...]:
        balances = await self.get_kyzma_balances(chat_id, user_ids, game_kind)
        return tuple(user_id for user_id, balance in balances.items() if balance < amount)

    async def charge_kyzma_coins_once(
        self,
        game_id: str,
        chat_id: int,
        user_ids: list[int] | tuple[int, ...],
        game_kind: str,
        amount: int,
        reason: str,
    ) -> KyzmaChargeResult:
        distinct_user_ids = tuple(dict.fromkeys(user_ids))
        if amount <= 0 or not distinct_user_ids:
            return KyzmaChargeResult(True, already_charged=True)
        try:
            with self.conn:
                for user_id in distinct_user_ids:
                    self._insert_user_stats_ignore(chat_id, user_id, game_kind)
                placeholders = ",".join("?" for _ in distinct_user_ids)
                existing_rows = self.conn.execute(
                    f"""
                    SELECT user_id
                    FROM kyzma_coin_events
                    WHERE game_id = ? AND reason = ? AND user_id IN ({placeholders})
                    """,
                    (game_id, reason, *distinct_user_ids),
                ).fetchall()
                charged_user_ids = {int(row["user_id"]) for row in existing_rows}
                if charged_user_ids == set(distinct_user_ids):
                    return KyzmaChargeResult(True, already_charged=True)

                balances = await self.get_kyzma_balances(chat_id, distinct_user_ids, game_kind)
                insufficient = tuple(
                    user_id
                    for user_id in distinct_user_ids
                    if user_id not in charged_user_ids and balances.get(user_id, 0) < amount
                )
                if insufficient:
                    raise _InsufficientKyzmaBalance(insufficient)

                now = now_text()
                for user_id in distinct_user_ids:
                    if user_id in charged_user_ids:
                        continue
                    updated = self.conn.execute(
                        """
                        UPDATE chat_user_stats
                        SET kyzma_coin_balance = kyzma_coin_balance - ?
                        WHERE chat_id = ? AND user_id = ? AND game_kind = ?
                            AND kyzma_coin_balance >= ?
                        """,
                        (amount, chat_id, user_id, game_kind, amount),
                    )
                    if updated.rowcount != 1:
                        raise _InsufficientKyzmaBalance((user_id,))
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO kyzma_coin_events (
                            game_id, chat_id, user_id, game_kind, amount, multiplier, reason, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (game_id, chat_id, user_id, game_kind, -amount, None, reason, now),
                    )
        except _InsufficientKyzmaBalance as exc:
            return KyzmaChargeResult(False, exc.user_ids)
        return KyzmaChargeResult(True)

    async def award_kyzma_coins_once(
        self,
        game_id: str,
        chat_id: int,
        user_id: int,
        game_kind: str,
        amount: int,
        multiplier: int | None,
        reason: str,
    ) -> bool:
        if amount <= 0:
            return False
        with self.conn:
            self._insert_user_stats_ignore(chat_id, user_id, game_kind)
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO kyzma_coin_events (
                    game_id, chat_id, user_id, game_kind, amount, multiplier, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (game_id, chat_id, user_id, game_kind, amount, multiplier, reason, now_text()),
            )
            if cursor.rowcount == 0:
                return False
            self.conn.execute(
                """
                UPDATE chat_user_stats
                SET kyzma_coin_balance = kyzma_coin_balance + ?
                WHERE chat_id = ? AND user_id = ? AND game_kind = ?
                """,
                (amount, chat_id, user_id, game_kind),
            )
            return True

    def _apply_stats_result(self, stats: ChatUserStats, new_rating: int, winner_user_id: int | None) -> None:
        won = winner_user_id == stats.user_id
        lost = winner_user_id is not None and not won
        draw = winner_user_id is None
        next_streak = stats.current_streak + 1 if won else 0
        next_best_streak = max(stats.best_streak, next_streak)
        self.conn.execute(
            """
            UPDATE chat_user_stats
            SET wins = wins + ?, losses = losses + ?, draws = draws + ?,
                rating = ?, current_streak = ?, best_streak = ?,
                games_played = games_played + 1
            WHERE chat_id = ? AND user_id = ? AND game_kind = ?
            """,
            (int(won), int(lost), int(draw), new_rating, next_streak, next_best_streak, stats.chat_id, stats.user_id, stats.game_kind),
        )

    async def get_user(self, telegram_user_id: int) -> DbUser:
        row = self.conn.execute(
            """
            SELECT telegram_user_id, username, first_name, last_name, language_code,
                created_at, updated_at
            FROM users WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"user {telegram_user_id} not found")
        return DbUser(**dict(row))

    def close(self) -> None:
        self.conn.close()


def database_path(database_url: str) -> Path:
    if database_url.startswith("sqlite://"):
        parsed = urlparse(database_url)
        if parsed.netloc and parsed.path:
            return Path(f"/{parsed.netloc}{parsed.path}")
        return Path(parsed.path.lstrip("/") or "bot.db")
    return Path(database_url)


def dump_state(state: Any) -> str:
    if hasattr(state, "to_json"):
        state = state.to_json()
    return json.dumps(state, separators=(",", ":"))


def row_to_game(row: sqlite3.Row) -> DbGame:
    data = dict(row)
    data["rated"] = bool(data["rated"])
    data["state"] = json.loads(data.pop("state_json"))
    return DbGame(**data)


def row_to_move(row: sqlite3.Row) -> DbMove:
    data = dict(row)
    data["state_after"] = json.loads(data.pop("state_after_json"))
    return DbMove(**data)


def elo_rating(rating: int, opponent_rating: int, score: float) -> int:
    expected = 1.0 / (1.0 + math.pow(10, (opponent_rating - rating) / 400.0))
    return max(0, round(rating + 32.0 * (score - expected)))


def ordered_pair(left: int, right: int) -> tuple[int, int]:
    return (left, right) if left <= right else (right, left)


GAME_SELECT = """
SELECT
    id, chat_id, message_id, inline_message_id, game_kind, status, rated, state_json,
    current_turn_user_id, black_user_id, white_user_id,
    winner_user_id, result_reason, created_at, updated_at, finished_at
FROM games
"""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    telegram_user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chats (
    telegram_chat_id INTEGER PRIMARY KEY,
    title TEXT,
    kind TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER,
    inline_message_id TEXT,
    game_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    rated INTEGER NOT NULL DEFAULT 1,
    state_json TEXT NOT NULL,
    current_turn_user_id INTEGER,
    black_user_id INTEGER NOT NULL,
    white_user_id INTEGER NOT NULL,
    winner_user_id INTEGER,
    result_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    FOREIGN KEY(chat_id) REFERENCES chats(telegram_chat_id),
    FOREIGN KEY(current_turn_user_id) REFERENCES users(telegram_user_id),
    FOREIGN KEY(black_user_id) REFERENCES users(telegram_user_id),
    FOREIGN KEY(white_user_id) REFERENCES users(telegram_user_id),
    FOREIGN KEY(winner_user_id) REFERENCES users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    move_number INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    move_text TEXT NOT NULL,
    state_after_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(game_id) REFERENCES games(id),
    FOREIGN KEY(user_id) REFERENCES users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS chat_user_stats (
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
    starter_kyzma_granted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id, game_kind),
    FOREIGN KEY(chat_id) REFERENCES chats(telegram_chat_id),
    FOREIGN KEY(user_id) REFERENCES users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS kyzma_coin_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    game_kind TEXT NOT NULL,
    amount INTEGER NOT NULL,
    multiplier INTEGER,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(chat_id) REFERENCES chats(telegram_chat_id),
    FOREIGN KEY(user_id) REFERENCES users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS head_to_head_stats (
    chat_id INTEGER NOT NULL,
    user_a_id INTEGER NOT NULL,
    user_b_id INTEGER NOT NULL,
    game_kind TEXT NOT NULL,
    user_a_wins INTEGER NOT NULL DEFAULT 0,
    user_b_wins INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_a_id, user_b_id, game_kind),
    FOREIGN KEY(chat_id) REFERENCES chats(telegram_chat_id),
    FOREIGN KEY(user_a_id) REFERENCES users(telegram_user_id),
    FOREIGN KEY(user_b_id) REFERENCES users(telegram_user_id)
);

CREATE TABLE IF NOT EXISTS inline_invites (
    inline_message_id TEXT PRIMARY KEY,
    challenger_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_games_chat_id ON games(chat_id);
CREATE INDEX IF NOT EXISTS idx_games_active_message ON games(chat_id, message_id) WHERE finished_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_games_chat_status ON games(chat_id, game_kind, status);
CREATE INDEX IF NOT EXISTS idx_moves_game_move_number ON moves(game_id, move_number);
CREATE INDEX IF NOT EXISTS idx_chat_user_stats_leaderboard ON chat_user_stats(chat_id, game_kind, rating DESC, wins DESC);
CREATE INDEX IF NOT EXISTS idx_kyzma_coin_events_user ON kyzma_coin_events(chat_id, user_id, game_kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kyzma_coin_events_once
    ON kyzma_coin_events(game_id, user_id, reason);
CREATE UNIQUE INDEX IF NOT EXISTS idx_games_unique_active_invite
    ON games(chat_id, message_id)
    WHERE finished_at IS NULL AND message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_games_unique_inline_message
    ON games(inline_message_id)
    WHERE inline_message_id IS NOT NULL AND finished_at IS NULL;
"""


KYZMA_COIN_EVENTS_UNIQUE_GAME_ID_MIGRATION_SQL = """
PRAGMA foreign_keys = OFF;

ALTER TABLE kyzma_coin_events RENAME TO kyzma_coin_events_old_unique_game_id;

CREATE TABLE kyzma_coin_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    game_kind TEXT NOT NULL,
    amount INTEGER NOT NULL,
    multiplier INTEGER,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(chat_id) REFERENCES chats(telegram_chat_id),
    FOREIGN KEY(user_id) REFERENCES users(telegram_user_id)
);

INSERT OR IGNORE INTO kyzma_coin_events (
    id, game_id, chat_id, user_id, game_kind, amount, multiplier, reason, created_at
)
SELECT id, game_id, chat_id, user_id, game_kind, amount, multiplier, reason, created_at
FROM kyzma_coin_events_old_unique_game_id;

DROP TABLE kyzma_coin_events_old_unique_game_id;

PRAGMA foreign_keys = ON;
"""


EARLY_GAMES_MIGRATION_SQL = """
PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS users (
    telegram_user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chats (
    telegram_chat_id INTEGER PRIMARY KEY,
    title TEXT,
    kind TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO users (
    telegram_user_id, username, first_name, last_name, language_code, created_at, updated_at
)
VALUES (0, NULL, 'Unknown player', NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

INSERT OR IGNORE INTO chats (telegram_chat_id, title, kind, created_at, updated_at)
SELECT DISTINCT chat_id, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM games;

CREATE TABLE games_new (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER,
    inline_message_id TEXT,
    game_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    rated INTEGER NOT NULL DEFAULT 1,
    state_json TEXT NOT NULL,
    current_turn_user_id INTEGER,
    black_user_id INTEGER NOT NULL,
    white_user_id INTEGER NOT NULL,
    winner_user_id INTEGER,
    result_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

INSERT INTO games_new (
    id, chat_id, message_id, inline_message_id, game_kind, status, rated, state_json,
    current_turn_user_id, black_user_id, white_user_id, created_at, updated_at
)
SELECT id, chat_id, message_id, NULL, kind, 'waiting_for_players', 1,
    state_json, NULL, 0, 0, created_at, updated_at
FROM games;

DROP TABLE games;
ALTER TABLE games_new RENAME TO games;
PRAGMA foreign_keys = ON;
"""
