from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter

logger = logging.getLogger(__name__)


async def edit_message_text_with_retry(bot, *, attempts: int = 3, **kwargs: Any) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            await bot.edit_message_text(**kwargs)
            return True
        except BadRequest as error:
            if "message is not modified" in str(error).lower():
                return True
            logger.warning(
                "Telegram rejected a board message edit",
                extra={"attempt": attempt, "error": str(error)},
            )
            return False
        except Forbidden as error:
            logger.warning("Telegram board message is unavailable", extra={"error": str(error)})
            return False
        except RetryAfter as error:
            delay = retry_after_seconds(error.retry_after) + 0.25
            if attempt == attempts:
                logger.warning(
                    "Telegram board edit remained rate-limited after retries",
                    extra={"retry_after": delay},
                )
                return False
            logger.warning(
                "Telegram rate-limited a board edit; retrying in %.2f seconds",
                delay,
            )
            await asyncio.sleep(delay)
        except NetworkError as error:
            if attempt == attempts:
                logger.warning(
                    "Telegram board edit failed after retries; the next button tap will refresh it",
                    extra={"attempts": attempts, "error": str(error)},
                )
                return False
            await asyncio.sleep(0.5 * attempt)
    return False


async def send_message_with_retry(bot, *, attempts: int = 3, **kwargs: Any) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            await bot.send_message(**kwargs)
            return True
        except RetryAfter as error:
            delay = retry_after_seconds(error.retry_after) + 0.25
            if attempt == attempts:
                logger.warning("Telegram broadcast remained rate-limited", extra={"retry_after": delay})
                return False
            await asyncio.sleep(delay)
        except (BadRequest, Forbidden) as error:
            logger.warning(
                "Telegram rejected an admin broadcast destination",
                extra={"chat_id": kwargs.get("chat_id"), "error": str(error)},
            )
            return False
        except NetworkError as error:
            if attempt == attempts:
                logger.warning(
                    "Telegram broadcast failed after retries",
                    extra={"chat_id": kwargs.get("chat_id"), "error": str(error)},
                )
                return False
            await asyncio.sleep(0.5 * attempt)
    return False


def retry_after_seconds(value: int | float | timedelta) -> float:
    if isinstance(value, timedelta):
        return value.total_seconds()
    return float(value)
