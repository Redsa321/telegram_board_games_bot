POSTGRES_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS shared;
CREATE SCHEMA IF NOT EXISTS board_games;

CREATE TABLE IF NOT EXISTS board_games.schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shared.users (
    telegram_user_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    language_code VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shared.chats (
    telegram_chat_id BIGINT PRIMARY KEY,
    title VARCHAR(255),
    kind VARCHAR(32),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS board_games.chat_registry (
    chat_id BIGINT PRIMARY KEY REFERENCES shared.chats(telegram_chat_id),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shared.economy_settings (
    key VARCHAR(64) PRIMARY KEY,
    integer_value BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO shared.economy_settings (key, integer_value)
VALUES ('starter_balance', 100)
ON CONFLICT(key) DO NOTHING;

CREATE TABLE IF NOT EXISTS shared.global_wallets (
    user_id BIGINT PRIMARY KEY REFERENCES shared.users(telegram_user_id),
    kyzma_coin_balance BIGINT NOT NULL DEFAULT 0 CHECK (kyzma_coin_balance >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS board_games.games (
    id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL REFERENCES shared.chats(telegram_chat_id),
    message_id BIGINT,
    inline_message_id TEXT,
    game_kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    rated INTEGER NOT NULL DEFAULT 1,
    state_json TEXT NOT NULL,
    current_turn_user_id BIGINT REFERENCES shared.users(telegram_user_id),
    black_user_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    white_user_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    winner_user_id BIGINT REFERENCES shared.users(telegram_user_id),
    result_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS board_games.moves (
    id BIGSERIAL PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES board_games.games(id),
    move_number INTEGER NOT NULL,
    user_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    move_text TEXT NOT NULL,
    state_after_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS board_games.chat_user_stats (
    chat_id BIGINT NOT NULL REFERENCES shared.chats(telegram_chat_id),
    user_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    game_kind VARCHAR(32) NOT NULL,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    rating INTEGER NOT NULL DEFAULT 1000,
    current_streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    kyzma_coin_balance BIGINT NOT NULL DEFAULT 0,
    starter_kyzma_granted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id, game_kind)
);

CREATE TABLE IF NOT EXISTS board_games.global_user_stats (
    user_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    game_kind VARCHAR(32) NOT NULL,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    rating INTEGER NOT NULL DEFAULT 1000,
    current_streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, game_kind)
);

CREATE TABLE IF NOT EXISTS board_games.matchmaking_queue (
    user_id BIGINT PRIMARY KEY REFERENCES shared.users(telegram_user_id),
    chat_id BIGINT NOT NULL REFERENCES shared.chats(telegram_chat_id),
    message_id BIGINT NOT NULL,
    game_kind VARCHAR(32) NOT NULL,
    rated INTEGER NOT NULL,
    anonymous INTEGER NOT NULL,
    rating INTEGER NOT NULL DEFAULT 1000,
    joined_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS board_games.game_views (
    game_id TEXT NOT NULL REFERENCES board_games.games(id),
    user_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    chat_id BIGINT NOT NULL REFERENCES shared.chats(telegram_chat_id),
    message_id BIGINT NOT NULL,
    PRIMARY KEY(game_id, user_id),
    UNIQUE(chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS shared.kyzma_coin_events (
    id BIGSERIAL PRIMARY KEY,
    game_id TEXT NOT NULL,
    chat_id BIGINT NOT NULL REFERENCES shared.chats(telegram_chat_id),
    user_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    game_kind VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL CHECK (amount <> 0),
    multiplier INTEGER,
    reason VARCHAR(64) NOT NULL,
    source_bot VARCHAR(32) NOT NULL DEFAULT 'board_games',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(game_id, user_id, reason)
);

CREATE TABLE IF NOT EXISTS board_games.head_to_head_stats (
    chat_id BIGINT NOT NULL REFERENCES shared.chats(telegram_chat_id),
    user_a_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    user_b_id BIGINT NOT NULL REFERENCES shared.users(telegram_user_id),
    game_kind VARCHAR(32) NOT NULL,
    user_a_wins INTEGER NOT NULL DEFAULT 0,
    user_b_wins INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_a_id, user_b_id, game_kind)
);

CREATE TABLE IF NOT EXISTS board_games.audit_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    chat_id BIGINT REFERENCES shared.chats(telegram_chat_id),
    user_id BIGINT REFERENCES shared.users(telegram_user_id),
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS board_games.inline_invites (
    inline_message_id TEXT PRIMARY KEY,
    challenger_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_games_chat_id ON board_games.games(chat_id);
CREATE INDEX IF NOT EXISTS idx_games_active_message ON board_games.games(chat_id, message_id)
    WHERE finished_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_games_chat_status ON board_games.games(chat_id, game_kind, status);
CREATE INDEX IF NOT EXISTS idx_moves_game_move_number ON board_games.moves(game_id, move_number);
CREATE INDEX IF NOT EXISTS idx_chat_user_stats_leaderboard
    ON board_games.chat_user_stats(chat_id, game_kind, rating DESC, wins DESC);
CREATE INDEX IF NOT EXISTS idx_global_user_stats_leaderboard
    ON board_games.global_user_stats(game_kind, rating DESC, wins DESC);
CREATE INDEX IF NOT EXISTS idx_matchmaking_queue_pool
    ON board_games.matchmaking_queue(game_kind, rated, joined_at);
CREATE INDEX IF NOT EXISTS idx_game_views_user ON board_games.game_views(user_id, game_id);
CREATE INDEX IF NOT EXISTS idx_kyzma_coin_events_user
    ON shared.kyzma_coin_events(chat_id, user_id, game_kind);
CREATE INDEX IF NOT EXISTS idx_audit_events_chat_created
    ON board_games.audit_events(chat_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_user_created
    ON board_games.audit_events(user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_games_unique_active_invite
    ON board_games.games(chat_id, message_id)
    WHERE finished_at IS NULL AND message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_games_unique_inline_message
    ON board_games.games(inline_message_id)
    WHERE inline_message_id IS NOT NULL AND finished_at IS NULL;

INSERT INTO board_games.schema_migrations (version)
VALUES ('0001_shared_postgresql')
ON CONFLICT(version) DO NOTHING;
"""
