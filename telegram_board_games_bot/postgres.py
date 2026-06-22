from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID


class PostgresRow(Mapping[str, Any]):
    def __init__(self, values: Mapping[str, Any]):
        self._values = {key: portable_value(value) for key, value in values.items()}
        self._keys = tuple(self._values)

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            key = self._keys[key]
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def keys(self) -> tuple[str, ...]:
        return self._keys


class PostgresCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self) -> PostgresRow | None:
        row = self._cursor.fetchone()
        if row is None:
            self._cursor.close()
            return None
        return PostgresRow(row)

    def fetchall(self) -> list[PostgresRow]:
        rows = [PostgresRow(row) for row in self._cursor.fetchall()]
        self._cursor.close()
        return rows


class PostgresConnection:
    """Small sqlite-like facade used while the bot transitions to PostgreSQL.

    The application already keeps transaction boundaries inside Database. This facade
    preserves that API while translating DB-API placeholders and SQLite's ignore syntax.
    """

    def __init__(self, database_url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:  # pragma: no cover - exercised by production setup
            raise RuntimeError("PostgreSQL requires the psycopg dependency") from error

        self._psycopg = psycopg
        self._dict_row = dict_row
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._advisory_locks: set[int] = set()
        self._connection = self._connect()
        self._transactions: list[Any] = []

    def _connect(self):
        connection = self._psycopg.connect(
            self._database_url,
            autocommit=True,
            row_factory=self._dict_row,
        )
        connection.execute("SET search_path TO board_games, shared, public")
        for lock_id in self._advisory_locks:
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(%s) AS acquired",
                (lock_id,),
            ).fetchone()["acquired"]
            if not acquired:
                connection.close()
                raise RuntimeError("the PostgreSQL bot runtime lock was acquired by another process")
        return connection

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> PostgresCursor:
        if self._connection.closed:
            self._connection = self._connect()
        translated = postgres_sql(sql)
        cursor = self._connection.cursor()
        cursor.execute(translated, tuple(parameters))
        result = PostgresCursor(cursor)
        if cursor.description is None:
            cursor.close()
        return result

    def executescript(self, sql: str) -> None:
        for statement in split_sql_script(sql):
            self.execute(statement)

    @property
    def in_transaction(self) -> bool:
        return bool(self._transactions)

    def commit(self) -> None:
        # Statements outside an explicit context run in autocommit mode. Context-managed
        # transactions are committed by __exit__, matching sqlite's connection context.
        return None

    def close(self) -> None:
        self._connection.close()

    def acquire_advisory_lock(self, lock_id: int) -> bool:
        row = self.execute("SELECT pg_try_advisory_lock(?) AS acquired", (lock_id,)).fetchone()
        acquired = bool(row and row["acquired"])
        if acquired:
            self._advisory_locks.add(lock_id)
        return acquired

    def release_advisory_lock(self, lock_id: int) -> None:
        if lock_id not in self._advisory_locks or self._connection.closed:
            self._advisory_locks.discard(lock_id)
            return
        self.execute("SELECT pg_advisory_unlock(?)", (lock_id,)).fetchone()
        self._advisory_locks.discard(lock_id)

    def __enter__(self) -> "PostgresConnection":
        transaction = self._connection.transaction()
        transaction.__enter__()
        self._transactions.append(transaction)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        transaction = self._transactions.pop()
        transaction.__exit__(exc_type, exc_value, traceback)


def postgres_sql(sql: str) -> str:
    translated = sql.strip().rstrip(";")
    ignore_insert = bool(re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", translated, re.IGNORECASE))
    translated = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        translated,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", translated, re.IGNORECASE):
        raise ValueError("INSERT OR REPLACE must be expressed with ON CONFLICT")
    translated = translated.replace("?", "%s")
    if ignore_insert and "ON CONFLICT" not in translated.upper():
        translated += " ON CONFLICT DO NOTHING"
    return translated


def split_sql_script(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def portable_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value
