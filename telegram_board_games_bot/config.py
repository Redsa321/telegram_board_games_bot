from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_url: str = "sqlite:///bot.db"
    admin_user_id: int | None = None
    feedback_chat_id: int | None = None

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
        )


def optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
