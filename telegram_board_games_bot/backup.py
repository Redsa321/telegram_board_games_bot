from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv

from .db import database_path, is_postgres_url


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


def backup_postgres(
    database_url: str,
    output_directory: Path,
    keep: int = 7,
    now: datetime | None = None,
) -> Path:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = output_directory / f"bot-{timestamp}.dump"
    environment = postgres_environment(database_url)
    try:
        subprocess.run(
            ["pg_dump", "--format=custom", "--file", str(backup_path)],
            check=True,
            env=environment,
        )
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    expire_backups(output_directory, "bot-*.dump", keep)
    return backup_path


def restore_postgres(backup_path: Path, database_url: str) -> None:
    if not backup_path.is_file():
        raise FileNotFoundError(backup_path)
    environment = postgres_environment(database_url)
    subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            environment["PGDATABASE"],
            str(backup_path),
        ],
        check=True,
        env=environment,
    )


def expire_backups(directory: Path, pattern: str, keep: int) -> None:
    backups = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    for expired in backups[keep:]:
        expired.unlink()


def normalized_postgres_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def postgres_environment(database_url: str) -> dict[str, str]:
    parsed = urlparse(normalized_postgres_url(database_url))
    environment = {**os.environ, "PGDATABASE": unquote(parsed.path.lstrip("/"))}
    if parsed.hostname:
        environment["PGHOST"] = parsed.hostname
    if parsed.port:
        environment["PGPORT"] = str(parsed.port)
    if parsed.username:
        environment["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        environment["PGPASSWORD"] = unquote(parsed.password)
    for query_name, environment_name in {
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
    }.items():
        values = parse_qs(parsed.query).get(query_name)
        if values:
            environment[environment_name] = values[-1]
    return environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back up or restore the configured database.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", type=Path)
    backup_parser.add_argument("--database-url")
    backup_parser.add_argument("--output", type=Path, default=Path("backups"))
    backup_parser.add_argument("--keep", type=int, default=7)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", type=Path, required=True)
    restore_parser.add_argument("--database", type=Path)
    restore_parser.add_argument("--database-url")
    return parser


def configured_database_path() -> Path:
    load_dotenv()
    return database_path(os.getenv("DATABASE_URL", "sqlite:///bot.db"))


def configured_database_url() -> str:
    load_dotenv()
    return os.getenv("DATABASE_URL", "sqlite:///bot.db")


def main() -> None:
    args = build_parser().parse_args()
    configured_url = args.database_url or configured_database_url()
    if args.database is not None:
        configured_url = str(args.database)
    if args.command == "backup":
        if is_postgres_url(configured_url):
            print(backup_postgres(configured_url, args.output, args.keep))
        else:
            print(backup_database(database_path(configured_url), args.output, args.keep))
    else:
        if is_postgres_url(configured_url):
            restore_postgres(args.backup, configured_url)
            print("PostgreSQL")
        else:
            target_path = database_path(configured_url)
            restore_database(args.backup, target_path)
            print(target_path)


if __name__ == "__main__":
    main()
