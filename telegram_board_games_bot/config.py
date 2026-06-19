from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_url: str = "sqlite:///bot.db"

    @classmethod
    def from_env(cls) -> "Config":
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise RuntimeError("BOT_TOKEN is not set")
        return cls(
            bot_token=bot_token,
            database_url=os.getenv("DATABASE_URL", "sqlite:///bot.db"),
        )

