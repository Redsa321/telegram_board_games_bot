# Changelog

## Unreleased

### Changed

- Added PostgreSQL production persistence with isolated `shared`, `board_games`, and `siski` schemas
- Replaced cross-process SQLite wallet writes with an atomic shared wallet and coin ledger
- Added verified SQLite importers and PostgreSQL `pg_dump`/`pg_restore` operations
- Separated shared chat metadata from per-bot group membership for safe broadcasts

## 0.1.0-beta.1 - 2026-06-20

First public beta.

### Added

- Draughts and chess with local, inline, robot, and global game modes
- Rated and unrated games, Elo ratings, ranks, kyzma-coins, daily claims, and starter coins
- Global matchmaking with anonymous display mode and configurable per-move timeouts
- Local/global stats and leaderboards for draughts and chess
- Global queue/setup expiry, game resume, cancellation, and move-timeout forfeits
- Draughts threefold-repetition and no-progress draw detection
- Feedback, privacy, about, and administrator status commands
- Single-instance process lock and checked SQLite backup/restore tooling
- Lubuntu systemd service and daily backup timer

### Known Beta Limits

- Global games are synchronized through two private bot messages rather than a dedicated web client
- Anonymous mode hides display names but does not anonymize stored Telegram IDs
- In-progress local games depend on their original Telegram message remaining available
