from __future__ import annotations

import asyncio
import logging
from html import escape

from telegram import Chat, Message, ReplyParameters, Update, User
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut
from telegram.ext import ContextTypes

from . import i18n
from .db import (
    Database,
    FinishGame,
    GameOutcome,
    GameStateUpdate,
    NewGame,
    UpsertChat,
    UpsertUser,
)
from .economy import (
    CHESS_PRIZE_MULTIPLIER_FACTOR,
    CHESS_PVP_COST_MULTIPLIER,
    award_finished_game_currency,
    claim_daily_kyzma_bonus,
    configure_pvp_prize,
    configure_robot_prize,
)
from .games.chess_game import ChessState
from .games.chess_robot import chess_robot_name, chess_robot_user_id
from .games.draughts import DraughtsState, GameStatus, PieceColor
from .games.robot import RobotDifficulty, robot_name, robot_user_id
from .i18n import Lang
from .render.chess_board import (
    render_chess_invite_keyboard,
    render_chess_invite_message,
    render_chess_keyboard,
    render_chess_message,
    render_chess_robot_difficulty_keyboard,
)
from .render.text_board import (
    render_draughts_invite_keyboard,
    render_draughts_invite_message,
    render_draughts_keyboard,
    render_draughts_message,
    render_robot_difficulty_keyboard,
)


GAME_KIND_DRAUGHTS = "draughts"
GAME_KIND_CHESS = "chess"
GAME_KIND_WALLET = GAME_KIND_DRAUGHTS
logger = logging.getLogger(__name__)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    lang = i18n.user_lang(update.effective_user)
    await update.effective_message.reply_text(i18n.welcome(lang))


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    lang = i18n.user_lang(update.effective_user)
    text = f"{i18n.command_list_text(lang)}\n\n{i18n.help_rules(lang)}\n\n{i18n.help_footer(lang)}"
    await update.effective_message.reply_text(text)


async def handle_play_draughts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    challenger_id = telegram_user_id(user)
    lang = i18n.user_lang(user)
    await database.upsert_user(upsert_user_from_telegram(user))
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    challenger_value = await database.get_kyzma_value(msg.chat_id, challenger_id, GAME_KIND_DRAUGHTS)
    await msg.reply_text(
        render_draughts_invite_message(display_name(user), lang, challenger_value),
        reply_markup=render_draughts_invite_keyboard(challenger_id, lang),
    )


async def handle_play_chess(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    challenger_id = telegram_user_id(user)
    lang = i18n.user_lang(user)
    await database.upsert_user(upsert_user_from_telegram(user))
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    challenger_value = await database.get_kyzma_value(msg.chat_id, challenger_id, GAME_KIND_CHESS)
    await msg.reply_text(
        render_chess_invite_message(display_name(user), lang, challenger_value),
        reply_markup=render_chess_invite_keyboard(challenger_id, lang),
    )


async def handle_play_robot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    lang = i18n.user_lang(user)
    await database.upsert_user(upsert_user_from_telegram(user))
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    await reply_text_with_retry(
        msg,
        i18n.robot_difficulty_prompt(lang),
        reply_markup=render_robot_difficulty_keyboard(lang),
    )


async def handle_play_chess_robot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    lang = i18n.user_lang(user)
    await database.upsert_user(upsert_user_from_telegram(user))
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    await reply_text_with_retry(
        msg,
        i18n.chess_robot_difficulty_prompt(lang),
        reply_markup=render_chess_robot_difficulty_keyboard(lang),
    )


async def create_draughts_game_message(
    bot,
    database: Database,
    chat_id: int,
    message_id: int | None,
    black_user_id: int,
    white_user_id: int,
    rated: bool,
):
    state = DraughtsState.new(black_user_id, white_user_id)
    if rated and chat_id != 0:
        await configure_pvp_prize(database, chat_id, black_user_id, white_user_id, GAME_KIND_DRAUGHTS, state)
    db_game = await database.create_game(NewGame(
        chat_id=chat_id,
        message_id=message_id,
        inline_message_id=None,
        game_kind=GAME_KIND_DRAUGHTS,
        status=status_text(state),
        rated=rated,
        state=state,
        current_turn_user_id=state.current_user_id(),
        black_user_id=black_user_id,
        white_user_id=white_user_id,
    ))
    black = await database.get_user(black_user_id)
    white = await database.get_user(white_user_id)
    black_name = display_name_from_db_user(black)
    white_name = display_name_from_db_user(white)
    lang = i18n.db_user_lang(black)
    text = render_draughts_message(state, black_name, white_name, rated, lang)
    keyboard = render_draughts_keyboard(db_game.id, state, lang)
    if message_id is not None:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
    else:
        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        await database.update_game_state(GameStateUpdate(
            game_id=db_game.id,
            message_id=sent.message_id,
            status=status_text(state),
            state=state,
            current_turn_user_id=state.current_user_id(),
        ))
    return db_game


async def create_chess_game_message(
    bot,
    database: Database,
    chat_id: int,
    message_id: int | None,
    white_user_id: int,
    black_user_id: int,
    rated: bool,
):
    state = ChessState.new(white_user_id, black_user_id)
    if rated and chat_id != 0:
        await configure_pvp_prize(
            database,
            chat_id,
            black_user_id,
            white_user_id,
            GAME_KIND_CHESS,
            state,
            cost_multiplier=CHESS_PVP_COST_MULTIPLIER,
            prize_multiplier_factor=CHESS_PRIZE_MULTIPLIER_FACTOR,
        )
    db_game = await database.create_game(NewGame(
        chat_id=chat_id,
        message_id=message_id,
        inline_message_id=None,
        game_kind=GAME_KIND_CHESS,
        status=status_text(state),
        rated=rated,
        state=state,
        current_turn_user_id=state.current_user_id(),
        black_user_id=black_user_id,
        white_user_id=white_user_id,
    ))
    white = await database.get_user(white_user_id)
    black = await database.get_user(black_user_id)
    lang = i18n.db_user_lang(white)
    text = render_chess_message(
        state,
        display_name_from_db_user(white),
        display_name_from_db_user(black),
        rated,
        lang,
    )
    keyboard = render_chess_keyboard(db_game.id, state, lang)
    if message_id is not None:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
    else:
        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        await database.update_game_state(GameStateUpdate(
            game_id=db_game.id,
            message_id=sent.message_id,
            status=status_text(state),
            state=state,
            current_turn_user_id=state.current_user_id(),
        ))
    return db_game


async def create_robot_game_message(
    bot,
    database: Database,
    chat_id: int,
    message_id: int | None,
    human: User,
    difficulty: RobotDifficulty,
):
    human_id = telegram_user_id(human)
    robot_id = robot_user_id(difficulty)
    await database.upsert_user(upsert_user_from_telegram(human))
    robot = await ensure_robot_user(database, difficulty)
    human_db = await database.get_user(human_id)
    state = DraughtsState.new(robot_id, human_id)
    state.robot_user_id = robot_id
    state.robot_difficulty = difficulty.value
    configure_robot_prize(state, difficulty.value)
    db_game = await database.create_game(NewGame(
        chat_id=chat_id,
        message_id=message_id,
        inline_message_id=None,
        game_kind=GAME_KIND_DRAUGHTS,
        status=status_text(state),
        rated=False,
        state=state,
        current_turn_user_id=state.current_user_id(),
        black_user_id=robot_id,
        white_user_id=human_id,
    ))
    lang = i18n.user_lang(human)
    text = render_draughts_message(
        state,
        display_name_from_db_user(robot),
        display_name_from_db_user(human_db),
        False,
        lang,
    )
    keyboard = render_draughts_keyboard(db_game.id, state, lang)
    if message_id is not None:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
    else:
        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        await database.update_game_state(GameStateUpdate(
            game_id=db_game.id,
            message_id=sent.message_id,
            status=status_text(state),
            state=state,
            current_turn_user_id=state.current_user_id(),
        ))
    return db_game


async def create_chess_robot_game_message(
    bot,
    database: Database,
    chat_id: int,
    message_id: int | None,
    human: User,
    difficulty: RobotDifficulty,
):
    human_id = telegram_user_id(human)
    robot_id = chess_robot_user_id(difficulty)
    await database.upsert_user(upsert_user_from_telegram(human))
    robot = await ensure_chess_robot_user(database, difficulty)
    human_db = await database.get_user(human_id)
    state = ChessState.new(human_id, robot_id)
    state.robot_user_id = robot_id
    state.robot_difficulty = difficulty.value
    configure_robot_prize(state, difficulty.value, prize_multiplier_factor=CHESS_PRIZE_MULTIPLIER_FACTOR)
    db_game = await database.create_game(NewGame(
        chat_id=chat_id,
        message_id=message_id,
        inline_message_id=None,
        game_kind=GAME_KIND_CHESS,
        status=status_text(state),
        rated=False,
        state=state,
        current_turn_user_id=state.current_user_id(),
        black_user_id=robot_id,
        white_user_id=human_id,
    ))
    lang = i18n.user_lang(human)
    text = render_chess_message(
        state,
        display_name_from_db_user(human_db),
        display_name_from_db_user(robot),
        False,
        lang,
    )
    keyboard = render_chess_keyboard(db_game.id, state, lang)
    if message_id is not None:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
    else:
        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        await database.update_game_state(GameStateUpdate(
            game_id=db_game.id,
            message_id=sent.message_id,
            status=status_text(state),
            state=state,
            current_turn_user_id=state.current_user_id(),
        ))
    return db_game


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    user_id = telegram_user_id(user)
    lang = i18n.user_lang(user)
    await database.upsert_user(upsert_user_from_telegram(user))
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    stats = await database.ensure_user_stats(msg.chat_id, user_id, GAME_KIND_DRAUGHTS)
    await msg.reply_text(
        render_stats_text(lang, stats, user),
        parse_mode=ParseMode.HTML,
        reply_parameters=ReplyParameters(message_id=msg.message_id),
    )


async def handle_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    user_id = telegram_user_id(user)
    lang = i18n.user_lang(user)
    await database.upsert_user(upsert_user_from_telegram(user))
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    stats = await database.ensure_user_stats(msg.chat_id, user_id, GAME_KIND_DRAUGHTS)
    await msg.reply_text(
        render_wallet_text(lang, stats, user),
        parse_mode=ParseMode.HTML,
        reply_parameters=ReplyParameters(message_id=msg.message_id),
    )


async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    user_id = telegram_user_id(user)
    lang = i18n.user_lang(user)
    await database.upsert_user(upsert_user_from_telegram(user))
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    result = await claim_daily_kyzma_bonus(database, msg.chat_id, user_id, GAME_KIND_DRAUGHTS)
    text = (
        i18n.daily_claim_success(lang, result.amount, result.balance)
        if result.claimed
        else i18n.daily_claim_already_claimed(lang, result.balance)
    )
    await msg.reply_text(
        text,
        reply_parameters=ReplyParameters(message_id=msg.message_id),
    )


async def handle_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    if msg is None:
        return
    lang = i18n.user_lang(update.effective_user)
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    leaderboard = await database.get_group_leaderboard(msg.chat_id, GAME_KIND_DRAUGHTS, 10)
    await msg.reply_text(render_leaderboard_text(lang, leaderboard))


async def handle_resign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    user_id = telegram_user_id(user)
    lang = i18n.user_lang(user)
    reply = msg.reply_to_message
    if reply is None:
        await msg.reply_text(i18n.resign_reply_required(lang))
        return
    db_game = await database.get_active_game_by_message(msg.chat_id, reply.message_id)
    if db_game is None:
        await msg.reply_text(i18n.no_active_game_on_message(lang))
        return
    if db_game.game_kind != GAME_KIND_DRAUGHTS:
        await msg.reply_text(i18n.replied_game_not_draughts(lang))
        return
    state = DraughtsState.from_json(db_game.state)
    if state.status is not GameStatus.IN_PROGRESS:
        await msg.reply_text(i18n.game_not_started(lang))
        return
    resigning_color = state.user_color(user_id)
    if resigning_color is None:
        await msg.reply_text(i18n.not_playing_in_game(lang))
        return
    await resign_game(database, db_game, state, resigning_color)
    black = await database.get_user(db_game.black_user_id)
    white = await database.get_user(db_game.white_user_id)
    board_lang = i18n.db_user_lang(black)
    await context.bot.edit_message_text(
        chat_id=msg.chat_id,
        message_id=reply.message_id,
        text=render_draughts_message(
            state,
            display_name_from_db_user(black),
            display_name_from_db_user(white),
            db_game.rated,
            board_lang,
        ),
        reply_markup=render_draughts_keyboard(db_game.id, state, board_lang),
    )
    await msg.reply_text(i18n.game_resigned(lang))


async def resign_game(database: Database, db_game, state: DraughtsState, resigning_color: PieceColor) -> None:
    state.status = GameStatus.FINISHED
    state.winner = PieceColor.WHITE if resigning_color is PieceColor.BLACK else PieceColor.BLACK
    state.result_reason = "resignation"
    state.selected = None
    state.must_continue_from = None
    await database.finish_game(FinishGame(db_game.id, state.winner_user_id(), state.result_reason))
    await database.update_game_state(GameStateUpdate(db_game.id, db_game.message_id, status_text(state), state, None))
    if db_game.rated:
        await database.update_stats_after_game(GameOutcome(
            chat_id=db_game.chat_id,
            game_kind=GAME_KIND_DRAUGHTS,
            black_user_id=db_game.black_user_id,
            white_user_id=db_game.white_user_id,
            winner_user_id=state.winner_user_id(),
        ))
    await award_finished_game_currency(database, db_game, state, GAME_KIND_DRAUGHTS)


def render_stats_text(lang: Lang, stats, user: User | None = None, game_name: str | None = None) -> str:
    text = i18n.stats_text(lang, stats, game_name)
    if user is None:
        return text

    name = escape(stats_display_name(user))
    label = i18n.player_word(lang)
    return f"{label}: {name}\n{text}"


def render_wallet_text(lang: Lang, stats, user: User | None = None) -> str:
    text = i18n.wallet_text(lang, stats)
    if user is None:
        return text

    name = escape(stats_display_name(user))
    label = i18n.player_word(lang)
    return f"{label}: {name}\n{text}"


def render_leaderboard_text(lang: Lang, leaderboard) -> str:
    if not leaderboard:
        return i18n.leaderboard_empty(lang)
    rows = [
        (
            display_name_from_parts(entry.username, entry.first_name, entry.last_name, entry.user_id),
            entry.wins,
            entry.losses,
            entry.rating,
        )
        for entry in leaderboard
    ]
    return i18n.leaderboard_text(lang, rows)


def upsert_user_from_telegram(user: User) -> UpsertUser:
    return UpsertUser(
        telegram_user_id=telegram_user_id(user),
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
    )


async def ensure_robot_user(database: Database, difficulty: RobotDifficulty):
    return await database.upsert_user(UpsertUser(
        telegram_user_id=robot_user_id(difficulty),
        username=None,
        first_name=robot_name(difficulty),
        last_name=None,
        language_code=None,
    ))


async def ensure_chess_robot_user(database: Database, difficulty: RobotDifficulty):
    return await database.upsert_user(UpsertUser(
        telegram_user_id=chess_robot_user_id(difficulty),
        username=None,
        first_name=chess_robot_name(difficulty),
        last_name=None,
        language_code=None,
    ))


def upsert_chat_from_telegram(chat: Chat) -> UpsertChat:
    return UpsertChat(telegram_chat_id=chat.id, title=chat_title(chat), kind=chat.type)


def telegram_user_id(user: User) -> int:
    return int(user.id)


def chat_title(chat: Chat) -> str | None:
    if chat.title:
        return chat.title
    if chat.username:
        return f"@{chat.username}"
    if chat.first_name:
        return f"{chat.first_name} {chat.last_name}".strip() if chat.last_name else chat.first_name
    return None


def display_name(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name


def stats_display_name(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name


def display_name_from_db_user(user) -> str:
    return display_name_from_parts(user.username, user.first_name, user.last_name, user.telegram_user_id)


def display_name_from_parts(username: str | None, first_name: str | None, last_name: str | None, fallback_id: int) -> str:
    if username:
        return f"@{username}"
    if first_name and last_name:
        return f"{first_name} {last_name}"
    if first_name:
        return first_name
    return f"user {fallback_id}"


def status_text(state) -> str:
    return state.status.value


def get_database(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["database"]


async def reply_text_with_retry(message: Message, text: str, attempts: int = 3, **kwargs):
    request_kwargs = {
        "connect_timeout": 30,
        "read_timeout": 30,
        "write_timeout": 30,
        "pool_timeout": 30,
    }
    for attempt in range(1, attempts + 1):
        try:
            return await message.reply_text(text, **request_kwargs, **kwargs)
        except (TimedOut, NetworkError):
            logger.warning("telegram reply timed out, retrying", extra={"attempt": attempt})
            if attempt == attempts:
                raise
            await asyncio.sleep(attempt)
