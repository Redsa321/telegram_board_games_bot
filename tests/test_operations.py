import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from telegram_board_games_bot.backup import backup_database, restore_database
from telegram_board_games_bot.config import Config
from telegram_board_games_bot.db import Database, database_path
from telegram_board_games_bot.runtime_lock import ProcessLock


def test_process_lock_rejects_a_second_instance(tmp_path) -> None:
    first = ProcessLock(tmp_path / "bot.db.lock")
    second = ProcessLock(tmp_path / "bot.db.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="another bot process"):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_sqlite_backup_restore_and_retention(tmp_path) -> None:
    source_path = tmp_path / "bot.db"
    connection = sqlite3.connect(source_path)
    connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")
    connection.execute("INSERT INTO values_table VALUES ('original')")
    connection.commit()
    connection.close()
    backup_directory = tmp_path / "backups"
    now = datetime.now(UTC)

    first = backup_database(source_path, backup_directory, keep=2, now=now)
    second = backup_database(source_path, backup_directory, keep=2, now=now + timedelta(seconds=1))
    third = backup_database(source_path, backup_directory, keep=2, now=now + timedelta(seconds=2))

    assert not first.exists()
    assert second.exists()
    assert third.exists()
    connection = sqlite3.connect(source_path)
    connection.execute("UPDATE values_table SET value = 'changed'")
    connection.commit()
    connection.close()

    restore_database(third, source_path)

    connection = sqlite3.connect(source_path)
    assert connection.execute("SELECT value FROM values_table").fetchone()[0] == "original"
    connection.close()


def test_database_path_supports_relative_absolute_and_home_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert database_path("sqlite:///bot.db") == Path("bot.db")
    assert database_path("sqlite:////var/lib/board-bot/bot.db") == Path("/var/lib/board-bot/bot.db")
    assert database_path("~/.local/share/board-bot/bot.db") == tmp_path / ".local/share/board-bot/bot.db"


def test_database_creates_parent_directory_for_durable_path(tmp_path) -> None:
    path = tmp_path / "persistent" / "bot.db"

    database = Database.connect(str(path))
    database._run_migrations()

    assert path.is_file()
    database.close()


def test_config_parses_existing_database_guard(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_REQUIRE_EXISTING", "true")

    assert Config.from_env().require_existing_database is True
