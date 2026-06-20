from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def backup_database(
    database_path: Path,
    output_directory: Path,
    keep: int = 7,
    now: datetime | None = None,
) -> Path:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if not database_path.exists():
        raise FileNotFoundError(database_path)
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = output_directory / f"bot-{timestamp}.db"
    source = sqlite3.connect(database_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"backup integrity check failed: {integrity}")
    finally:
        destination.close()
        source.close()
    backups = sorted(output_directory.glob("bot-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for expired in backups[keep:]:
        expired.unlink()
    return backup_path


def restore_database(backup_path: Path, database_path: Path) -> None:
    if not backup_path.exists():
        raise FileNotFoundError(backup_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = database_path.with_name(f".{database_path.name}.restore-tmp")
    temporary_path.unlink(missing_ok=True)
    try:
        source = sqlite3.connect(backup_path)
        destination = sqlite3.connect(temporary_path)
        try:
            integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"source backup integrity check failed: {integrity}")
            source.backup(destination)
        finally:
            destination.close()
            source.close()
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    for suffix in ("-wal", "-shm"):
        database_path.with_name(f"{database_path.name}{suffix}").unlink(missing_ok=True)
    os.replace(temporary_path, database_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back up or restore the bot's SQLite database.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", type=Path, default=Path("bot.db"))
    backup_parser.add_argument("--output", type=Path, default=Path("backups"))
    backup_parser.add_argument("--keep", type=int, default=7)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", type=Path, required=True)
    restore_parser.add_argument("--database", type=Path, default=Path("bot.db"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "backup":
        print(backup_database(args.database, args.output, args.keep))
    else:
        restore_database(args.backup, args.database)
        print(args.database)


if __name__ == "__main__":
    main()
