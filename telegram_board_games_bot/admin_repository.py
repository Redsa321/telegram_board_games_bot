from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .db import Database


class AdminRepository:
    def __init__(self, database: Database):
        self.database = database

    def overview(self) -> dict[str, int]:
        row = self.database.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM users WHERE telegram_user_id > 0) AS users,
                (SELECT COUNT(*) FROM chats WHERE kind IN ('group', 'supergroup')) AS groups,
                (SELECT COUNT(*) FROM chats WHERE kind IN ('group', 'supergroup') AND is_active = 1) AS active_groups,
                (SELECT COUNT(*) FROM games) AS games,
                (SELECT COUNT(*) FROM games WHERE finished_at IS NULL AND status != 'finished') AS active_games,
                (SELECT COALESCE(SUM(kyzma_coin_balance), 0) FROM global_wallets) AS coin_supply
            """
        ).fetchone()
        return {key: int(row[key]) for key in row.keys()}

    def groups(self, search: str | None = None) -> list[dict[str, Any]]:
        parameters: list[Any] = []
        search_clause = ""
        if search:
            pattern = f"%{search.lower()}%"
            search_clause = """
                AND (
                    LOWER(COALESCE(c.title, '')) LIKE ?
                    OR CAST(c.telegram_chat_id AS TEXT) LIKE ?
                )
            """
            parameters.extend((pattern, pattern))
        rows = self.database.conn.execute(
            f"""
            SELECT
                c.telegram_chat_id AS chat_id,
                c.title,
                c.kind,
                c.is_active,
                c.updated_at,
                (SELECT COUNT(*) FROM games g WHERE g.chat_id = c.telegram_chat_id) AS games_count,
                (SELECT COUNT(DISTINCT s.user_id) FROM chat_user_stats s WHERE s.chat_id = c.telegram_chat_id) AS players_count,
                COALESCE(
                    (SELECT MAX(g.updated_at) FROM games g WHERE g.chat_id = c.telegram_chat_id),
                    c.updated_at
                ) AS last_activity
            FROM chats c
            WHERE c.kind IN ('group', 'supergroup')
            {search_clause}
            ORDER BY c.is_active DESC, LOWER(COALESCE(c.title, '')), c.telegram_chat_id
            """,
            parameters,
        ).fetchall()
        return [
            {
                "chat_id": int(row["chat_id"]),
                "title": row["title"] or "Untitled group",
                "kind": row["kind"],
                "is_active": bool(row["is_active"]),
                "games_count": int(row["games_count"]),
                "players_count": int(row["players_count"]),
                "last_activity": row["last_activity"],
            }
            for row in rows
        ]

    def users(self, search: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        parameters: list[Any] = []
        search_clause = ""
        if search:
            pattern = f"%{search.lower()}%"
            search_clause = """
                AND (
                    CAST(u.telegram_user_id AS TEXT) LIKE ?
                    OR LOWER(COALESCE(u.username, '')) LIKE ?
                    OR LOWER(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))) LIKE ?
                )
            """
            parameters.extend((pattern, pattern, pattern))
        parameters.append(max(1, min(limit, 500)))
        rows = self.database.conn.execute(
            f"""
            SELECT
                u.telegram_user_id AS user_id,
                u.username,
                u.first_name,
                u.last_name,
                u.language_code,
                u.updated_at,
                COALESCE(w.kyzma_coin_balance, 0) AS balance,
                COALESCE(MAX(CASE WHEN gs.game_kind = 'draughts' THEN gs.rating END), 1000) AS draughts_rating,
                COALESCE(MAX(CASE WHEN gs.game_kind = 'chess' THEN gs.rating END), 1000) AS chess_rating,
                COALESCE(SUM(gs.games_played), 0) AS global_games
            FROM users u
            LEFT JOIN global_wallets w ON w.user_id = u.telegram_user_id
            LEFT JOIN global_user_stats gs ON gs.user_id = u.telegram_user_id
            WHERE u.telegram_user_id > 0
            {search_clause}
            GROUP BY u.telegram_user_id
            ORDER BY u.updated_at DESC, u.telegram_user_id
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [
            {
                "user_id": int(row["user_id"]),
                "username": row["username"],
                "display_name": display_name(row),
                "language_code": row["language_code"],
                "balance": int(row["balance"]),
                "draughts_rating": int(row["draughts_rating"]),
                "chess_rating": int(row["chess_rating"]),
                "global_games": int(row["global_games"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def user_detail(self, user_id: int) -> dict[str, Any] | None:
        row = self.database.conn.execute(
            """
            SELECT
                u.telegram_user_id AS user_id,
                u.username,
                u.first_name,
                u.last_name,
                u.language_code,
                u.created_at,
                u.updated_at,
                COALESCE(w.kyzma_coin_balance, 0) AS balance
            FROM users u
            LEFT JOIN global_wallets w ON w.user_id = u.telegram_user_id
            WHERE u.telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        global_stats = [dict(stats) for stats in self.database.conn.execute(
            """
            SELECT game_kind, wins, losses, draws, rating, current_streak, best_streak, games_played
            FROM global_user_stats WHERE user_id = ? ORDER BY game_kind
            """,
            (user_id,),
        ).fetchall()]
        local_stats = [dict(stats) for stats in self.database.conn.execute(
            """
            SELECT
                s.chat_id,
                COALESCE(c.title, 'Unknown chat') AS chat_title,
                s.game_kind,
                s.wins,
                s.losses,
                s.draws,
                s.rating,
                s.current_streak,
                s.best_streak,
                s.games_played
            FROM chat_user_stats s
            LEFT JOIN chats c ON c.telegram_chat_id = s.chat_id
            WHERE s.user_id = ?
            ORDER BY s.games_played DESC, s.chat_id, s.game_kind
            """,
            (user_id,),
        ).fetchall()]
        coin_events = [dict(event) for event in self.database.conn.execute(
            """
            SELECT game_id, chat_id, game_kind, amount, multiplier, reason, created_at
            FROM kyzma_coin_events
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 50
            """,
            (user_id,),
        ).fetchall()]
        return {
            "user_id": int(row["user_id"]),
            "username": row["username"],
            "display_name": display_name(row),
            "language_code": row["language_code"],
            "balance": int(row["balance"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "global_stats": global_stats,
            "local_stats": local_stats,
            "coin_events": coin_events,
        }

    def events(self, chat_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        chat_filter = "" if chat_id is None else " AND g.chat_id = ?"
        parameters: tuple[Any, ...] = () if chat_id is None else (chat_id,)
        game_rows = self.database.conn.execute(
            f"""
            SELECT
                g.id AS game_id,
                g.chat_id,
                g.game_kind,
                g.rated,
                g.black_user_id,
                g.white_user_id,
                g.winner_user_id,
                g.result_reason,
                g.finished_at AS occurred_at,
                c.title AS chat_title,
                bu.username AS black_username,
                bu.first_name AS black_first_name,
                bu.last_name AS black_last_name,
                wu.username AS white_username,
                wu.first_name AS white_first_name,
                wu.last_name AS white_last_name,
                win.username AS winner_username,
                win.first_name AS winner_first_name,
                win.last_name AS winner_last_name
            FROM games g
            LEFT JOIN chats c ON c.telegram_chat_id = g.chat_id
            LEFT JOIN users bu ON bu.telegram_user_id = g.black_user_id
            LEFT JOIN users wu ON wu.telegram_user_id = g.white_user_id
            LEFT JOIN users win ON win.telegram_user_id = g.winner_user_id
            WHERE g.finished_at IS NOT NULL {chat_filter}
            ORDER BY g.finished_at DESC LIMIT {limit}
            """,
            parameters,
        ).fetchall()
        coin_filter = "" if chat_id is None else " AND e.chat_id = ?"
        coin_rows = self.database.conn.execute(
            f"""
            SELECT
                e.id,
                e.game_id,
                e.chat_id,
                e.user_id,
                e.game_kind,
                e.amount,
                e.multiplier,
                e.reason,
                e.created_at AS occurred_at,
                c.title AS chat_title,
                u.username,
                u.first_name,
                u.last_name
            FROM kyzma_coin_events e
            LEFT JOIN chats c ON c.telegram_chat_id = e.chat_id
            LEFT JOIN users u ON u.telegram_user_id = e.user_id
            WHERE 1 = 1 {coin_filter}
            ORDER BY e.created_at DESC LIMIT {limit}
            """,
            parameters,
        ).fetchall()
        audit_filter = "" if chat_id is None else " AND a.chat_id = ?"
        audit_rows = self.database.conn.execute(
            f"""
            SELECT
                a.id,
                a.event_type,
                a.chat_id,
                a.user_id,
                a.details_json,
                a.created_at AS occurred_at,
                c.title AS chat_title,
                u.username,
                u.first_name,
                u.last_name
            FROM audit_events a
            LEFT JOIN chats c ON c.telegram_chat_id = a.chat_id
            LEFT JOIN users u ON u.telegram_user_id = a.user_id
            WHERE 1 = 1 {audit_filter}
            ORDER BY a.created_at DESC LIMIT {limit}
            """,
            parameters,
        ).fetchall()

        events: list[dict[str, Any]] = []
        for row in game_rows:
            events.append({
                "id": f"game:{row['game_id']}",
                "type": "game_finished",
                "occurred_at": row["occurred_at"],
                "chat_id": int(row["chat_id"]),
                "chat_title": row["chat_title"],
                "game_id": row["game_id"],
                "game_kind": row["game_kind"],
                "rated": bool(row["rated"]),
                "black_user_id": int(row["black_user_id"]),
                "black_name": display_name(row, "black_", int(row["black_user_id"])),
                "white_user_id": int(row["white_user_id"]),
                "white_name": display_name(row, "white_", int(row["white_user_id"])),
                "winner_user_id": int(row["winner_user_id"]) if row["winner_user_id"] is not None else None,
                "winner_name": (
                    display_name(row, "winner_", int(row["winner_user_id"]))
                    if row["winner_user_id"] is not None
                    else None
                ),
                "reason": row["result_reason"],
            })
        for row in coin_rows:
            events.append({
                "id": f"coin:{row['id']}",
                "type": "coin_event",
                "occurred_at": row["occurred_at"],
                "chat_id": int(row["chat_id"]),
                "chat_title": row["chat_title"],
                "game_id": row["game_id"],
                "user_id": int(row["user_id"]),
                "user_name": display_name(row, fallback_id=int(row["user_id"])),
                "game_kind": row["game_kind"],
                "amount": int(row["amount"]),
                "multiplier": int(row["multiplier"]) if row["multiplier"] is not None else None,
                "reason": row["reason"],
            })
        for row in audit_rows:
            events.append({
                "id": f"audit:{row['id']}",
                "type": row["event_type"],
                "occurred_at": row["occurred_at"],
                "chat_id": int(row["chat_id"]) if row["chat_id"] is not None else None,
                "chat_title": row["chat_title"],
                "user_id": int(row["user_id"]) if row["user_id"] is not None else None,
                "user_name": (
                    display_name(row, fallback_id=int(row["user_id"]))
                    if row["user_id"] is not None
                    else None
                ),
                "details": json.loads(row["details_json"]),
            })
        events.sort(key=lambda event: parse_timestamp(event["occurred_at"]), reverse=True)
        return events[:limit]


def display_name(row: Any, prefix: str = "", fallback_id: int | None = None) -> str:
    username = row[f"{prefix}username"]
    if username:
        return f"@{username}"
    name = " ".join(
        part for part in (row[f"{prefix}first_name"], row[f"{prefix}last_name"]) if part
    ).strip()
    return name or f"User {fallback_id or row['user_id']}"


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
