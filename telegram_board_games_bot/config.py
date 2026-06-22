from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_url: str = "sqlite:///bot.db"
    admin_user_id: int | None = None
    feedback_chat_id: int | None = None
    require_existing_database: bool = False
    admin_web_token: str | None = None
    admin_web_host: str = "127.0.0.1"
    admin_web_port: int = 8080

    @classmethod
    def from_env(cls) -> "Config":
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise RuntimeError("BOT_TOKEN is not set")
        admin_user_id = optional_int_env("ADMIN_USER_ID")
        return cls(
            bot_token=bot_token,
            database_url=os.getenv("DATABASE_URL", "sqlite:///bot.db"),
            admin_user_id=admin_user_id,
            feedback_chat_id=optional_int_env("FEEDBACK_CHAT_ID") or admin_user_id,
            require_existing_database=optional_bool_env("DATABASE_REQUIRE_EXISTING", False),
            admin_web_token=os.getenv("ADMIN_WEB_TOKEN") or None,
            admin_web_host=os.getenv("ADMIN_WEB_HOST", "127.0.0.1"),
            admin_web_port=optional_int_env("ADMIN_WEB_PORT") or 8080,
        )


def optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error


def optional_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")
