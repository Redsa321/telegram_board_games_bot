from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.error import Conflict, NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    InlineQueryHandler,
)

from . import i18n
from .callbacks import handle_callback
from .chess_callbacks import handle_chess_callback
from .commands import (
    handle_about,
    handle_admin_groups,
    handle_admin_message,
    handle_admin_status,
    handle_bot_membership_update,
    handle_claim,
    handle_feedback,
    handle_help,
    handle_play_chess,
    handle_play_chess_robot,
    handle_play_draughts,
    handle_play_robot,
    handle_privacy,
    handle_resign,
    handle_start,
    handle_wallet,
)
from .config import Config
from .db import Database, database_path, is_postgres_url
from .global_matchmaking import (
    handle_cancel_global,
    handle_global_timeout_callback,
    handle_matchmaking_callback,
    handle_play_random,
    handle_resume_global,
    process_global_game_timeouts,
    process_matchmaking_queue,
)
from .inline import handle_chosen_inline_result, handle_inline_query
from .runtime_lock import ProcessLock
from .stats_views import (
    handle_global_stats_menu,
    handle_global_top_menu,
    handle_stats_menu,
    handle_stats_view_callback,
    handle_top_menu,
)

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
    if application.job_queue is None:
        logger.error("matchmaking scheduler is unavailable; install python-telegram-bot[job-queue]")
    else:
        application.job_queue.run_repeating(process_matchmaking_queue, interval=15, first=5, name="global-matchmaking")
        application.job_queue.run_repeating(process_global_game_timeouts, interval=5, first=5, name="global-game-timeouts")


async def handle_error(update, context) -> None:
    bot_data = context.application.bot_data
    bot_data["error_count"] = int(bot_data.get("error_count", 0)) + 1
    bot_data["last_error"] = f"{datetime.now(UTC).isoformat()} · {type(context.error).__name__}: {context.error}"
    if isinstance(context.error, Conflict):
        logger.error(
            "Telegram polling conflict: another process or webhook is using this bot token; stop the other bot instance"
        )
        return
    if isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning(
            "temporary Telegram network error: %s",
            context.error,
        )
        return
    if update is None and isinstance(context.error, TelegramError):
        logger.warning("Telegram polling error: %s", context.error)
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
    application.bot_data["config"] = config
    application.bot_data["error_count"] = 0
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("play_draughts", handle_play_draughts))
    application.add_handler(CommandHandler("play_chess", handle_play_chess))
    application.add_handler(CommandHandler("play_robot", handle_play_robot))
    application.add_handler(CommandHandler("play_chess_robot", handle_play_chess_robot))
    application.add_handler(CommandHandler("play_random", handle_play_random))
    application.add_handler(CommandHandler("cancel_global", handle_cancel_global))
    application.add_handler(CommandHandler("resume_global", handle_resume_global))
    application.add_handler(CommandHandler("global_stats", handle_global_stats_menu))
    application.add_handler(CommandHandler("stats", handle_stats_menu))
    application.add_handler(CommandHandler("wallet", handle_wallet))
    application.add_handler(CommandHandler("claim", handle_claim))
    application.add_handler(CommandHandler("top", handle_top_menu))
    application.add_handler(CommandHandler("global_top", handle_global_top_menu))
    application.add_handler(CommandHandler("feedback", handle_feedback))
    application.add_handler(CommandHandler("privacy", handle_privacy))
    application.add_handler(CommandHandler("about", handle_about))
    application.add_handler(CommandHandler("admin_status", handle_admin_status))
    application.add_handler(CommandHandler("admin_groups", handle_admin_groups))
    application.add_handler(CommandHandler("admin_message", handle_admin_message))
    application.add_handler(CommandHandler("resign", handle_resign))
    application.add_handler(ChatMemberHandler(handle_bot_membership_update, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(handle_matchmaking_callback, pattern=r"^mm:"))
    application.add_handler(CallbackQueryHandler(handle_global_timeout_callback, pattern=r"^gmt:"))
    application.add_handler(CallbackQueryHandler(handle_stats_view_callback, pattern=r"^st:"))
    application.add_handler(CallbackQueryHandler(handle_chess_callback, pattern=r"^ch:"))
    application.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^dg:"))
    application.add_handler(InlineQueryHandler(handle_inline_query))
    application.add_handler(ChosenInlineResultHandler(handle_chosen_inline_result))
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    config = Config.from_env()
    configured_database_path = None if is_postgres_url(config.database_url) else database_path(config.database_url)
    if config.require_existing_database and configured_database_path is not None and not configured_database_path.is_file():
        raise RuntimeError(
            f"configured database does not exist: {configured_database_path}. "
            "Refusing to create an empty replacement database."
        )
    database = Database.connect(config.database_url)
    lock_path = (
        database.path.with_name(f"{database.path.name}.lock")
        if database.path is not None
        else Path(".telegram-board-games-bot.lock")
    )
    process_lock = ProcessLock(lock_path)
    try:
        process_lock.acquire()
        database.acquire_bot_runtime_lock()
        database._run_migrations()
        logger.info("using persistent database: %s", database.storage_label)
        build_application(config, database).run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        database.release_bot_runtime_lock()
        database.close()
        process_lock.release()
