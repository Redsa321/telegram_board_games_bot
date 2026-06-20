import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from telegram_board_games_bot.backup import backup_database, restore_database
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
