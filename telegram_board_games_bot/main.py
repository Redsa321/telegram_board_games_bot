from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.error import NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    InlineQueryHandler,
)

from . import i18n
from .callbacks import handle_callback
from .chess_callbacks import handle_chess_callback
from .commands import (
    handle_claim,
    handle_help,
    handle_play_chess,
    handle_play_chess_robot,
    handle_play_draughts,
    handle_play_robot,
    handle_resign,
    handle_start,
    handle_stats,
    handle_top,
    handle_wallet,
)
from .config import Config
from .db import Database
from .inline import handle_chosen_inline_result, handle_inline_query


logger = logging.getLogger(__name__)


async def register_localized_commands(application: Application) -> None:
    for lang in i18n.ALL_LANGS:
        commands = [BotCommand(name, description) for name, description in i18n.bot_command_descriptions(lang)]
        for attempt in range(1, 4):
            try:
                await application.bot.set_my_commands(
                    commands,
                    language_code=lang.telegram_code,
                    connect_timeout=30,
                    read_timeout=30,
                    write_timeout=30,
                    pool_timeout=30,
                )
                logger.info("registered bot commands", extra={"language": lang.telegram_code or "default"})
                break
            except (TimedOut, NetworkError) as error:
                logger.warning(
                    "failed to register bot commands, will retry",
                    extra={"language": lang.telegram_code or "default", "attempt": attempt, "error": str(error)},
                )
                if attempt == 3:
                    logger.error(
                        "failed to register bot commands after retries",
                        extra={"language": lang.telegram_code or "default"},
                    )
                else:
                    await asyncio.sleep(attempt)
            except TelegramError:
                logger.exception("failed to register bot commands", extra={"language": lang.telegram_code or "default"})
                break


async def post_init(application: Application) -> None:
    await register_localized_commands(application)


async def handle_error(update, context) -> None:
    if isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning(
            "telegram network error while handling update",
            exc_info=(type(context.error), context.error, context.error.__traceback__),
        )
        return
    logger.exception(
        "telegram update handler failed",
        exc_info=(type(context.error), context.error, context.error.__traceback__),
    )


def build_application(config: Config, database: Database) -> Application:
    application = (
        Application.builder()
        .token(config.bot_token)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(60)
        .get_updates_write_timeout(30)
        .get_updates_pool_timeout(30)
        .post_init(post_init)
        .build()
    )
    application.bot_data["database"] = database
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("play_draughts", handle_play_draughts))
    application.add_handler(CommandHandler("play_chess", handle_play_chess))
    application.add_handler(CommandHandler("play_robot", handle_play_robot))
    application.add_handler(CommandHandler("play_chess_robot", handle_play_chess_robot))
    application.add_handler(CommandHandler("stats", handle_stats))
    application.add_handler(CommandHandler("wallet", handle_wallet))
    application.add_handler(CommandHandler("claim", handle_claim))
    application.add_handler(CommandHandler("top", handle_top))
    application.add_handler(CommandHandler("resign", handle_resign))
    application.add_handler(CallbackQueryHandler(handle_chess_callback, pattern=r"^ch:"))
    application.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^dg:"))
    application.add_handler(InlineQueryHandler(handle_inline_query))
    application.add_handler(ChosenInlineResultHandler(handle_chosen_inline_result))
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    database = Database.connect(config.database_url)
    try:
        database._run_migrations()
        build_application(config, database).run_polling()
    finally:
        database.close()
