from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram.error import BadRequest, Forbidden, NetworkError

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
        except NetworkError as error:
            if attempt == attempts:
                logger.warning(
                    "Telegram board edit failed after retries; the next button tap will refresh it",
                    extra={"attempts": attempts, "error": str(error)},
                )
                return False
            await asyncio.sleep(0.5 * attempt)
    return False
