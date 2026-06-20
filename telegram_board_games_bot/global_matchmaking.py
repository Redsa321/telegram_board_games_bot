from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import floor

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters, Update
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from .commands import (
    GAME_KIND_CHESS,
    GAME_KIND_DRAUGHTS,
    display_name_from_db_user,
    get_database,
    stats_display_name,
    telegram_user_id,
    upsert_chat_from_telegram,
    upsert_user_from_telegram,
)
from .db import (
    Database,
    FinishGame,
    GameOutcome,
    GameStateUpdate,
    GameView,
    MatchmakingEntry,
    NewGame,
    UpsertChat,
    now_text,
)
from .economy import (
    CHESS_PRIZE_MULTIPLIER_FACTOR,
    award_finished_game_currency,
    charge_pvp_entry_fee_once,
    multiplied_cost,
    set_kyzma_prize,
)
from .games.chess_game import ChessState, ChessStatus
from .games.draughts import DraughtsState, GameStatus
from .i18n import Lang
from .render.chess_board import render_chess_keyboard, render_chess_message
from .render.text_board import render_draughts_keyboard, render_draughts_message

GLOBAL_CHAT_ID = 0
DEFAULT_MOVE_TIMEOUTS = {
    GAME_KIND_DRAUGHTS: 120,
    GAME_KIND_CHESS: 180,
}
MOVE_TIMEOUT_OPTIONS = (60, 120, 180, 300, 600)
MATCHMAKING_QUEUE_LIFETIME = timedelta(minutes=30)
TIMEOUT_SETUP_LIFETIME = timedelta(minutes=5)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RatingRank:
    name: str
    minimum: int
    maximum: int | None
    draughts_cost: int


RATING_RANKS = (
    RatingRank("Bronze", 0, 899, 5),
    RatingRank("Silver", 900, 1099, 10),
    RatingRank("Gold", 1100, 1299, 15),
    RatingRank("Platinum", 1300, 1499, 25),
    RatingRank("Diamond", 1500, 1699, 40),
    RatingRank("Master", 1700, None, 60),
)


def rank_for_rating(rating: int) -> RatingRank:
    normalized = max(0, rating)
    return next(
        rank
        for rank in RATING_RANKS
        if normalized >= rank.minimum and (rank.maximum is None or normalized <= rank.maximum)
    )


def rank_game_cost(rank: RatingRank, game_kind: str) -> int:
    if game_kind == GAME_KIND_CHESS:
        return multiplied_cost(rank.draughts_cost, 1.5)
    return rank.draughts_cost


def match_rank_and_cost(left_rating: int, right_rating: int, game_kind: str) -> tuple[RatingRank, int]:
    average_rating = floor((left_rating + right_rating) / 2 + 0.5)
    rank = rank_for_rating(average_rating)
    return rank, rank_game_cost(rank, game_kind)


async def handle_play_random(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return
    if chat.type != ChatType.PRIVATE:
        await message.reply_text("Random matchmaking is available only in a private chat with the bot.")
        return
    database = get_database(context)
    await database.upsert_user(upsert_user_from_telegram(user))
    await database.upsert_chat(upsert_chat_from_telegram(chat))
    await database.ensure_global_wallet(telegram_user_id(user))
    if await database.get_active_global_game_for_user(telegram_user_id(user)) is not None:
        await message.reply_text("Finish your current global game before joining another queue.")
        return
    queued = await database.get_matchmaking_entry(telegram_user_id(user))
    if queued is not None:
        sent = await message.reply_text(queue_text(queued), reply_markup=queue_keyboard())
        await database.add_matchmaking_entry(MatchmakingEntry(
            user_id=queued.user_id,
            chat_id=sent.chat_id,
            message_id=sent.message_id,
            game_kind=queued.game_kind,
            rated=queued.rated,
            anonymous=queued.anonymous,
            rating=queued.rating,
            joined_at=queued.joined_at,
        ))
        return
    await message.reply_text(config_text(), reply_markup=config_keyboard())


async def handle_global_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    database = get_database(context)
    user_id = telegram_user_id(user)
    await database.upsert_user(upsert_user_from_telegram(user))
    wallet = await database.ensure_global_wallet(user_id)
    draughts = await database.ensure_global_user_stats(user_id, GAME_KIND_DRAUGHTS)
    chess = await database.ensure_global_user_stats(user_id, GAME_KIND_CHESS)
    await message.reply_text(
        global_stats_summary(draughts, chess, wallet.kyzma_coin_balance),
        reply_parameters=ReplyParameters(message_id=message.message_id),
    )


async def handle_cancel_global(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    database = get_database(context)
    user_id = telegram_user_id(user)
    queued = await database.remove_matchmaking_entry(user_id)
    if queued is not None:
        await safe_edit_message(
            context.bot,
            queued.chat_id,
            queued.message_id,
            "Matchmaking cancelled.",
            config_keyboard(queued.game_kind, queued.rated, queued.anonymous),
        )
        await message.reply_text("Your matchmaking search was cancelled.")
        return
    db_game = await database.get_active_global_game_for_user(user_id)
    if db_game is None:
        await message.reply_text("You have no active global queue or game.")
        return
    state = global_state_from_game(db_game)
    if state.status.value == "confirming":
        await cancel_global_timeout(context.bot, database, db_game, state)
        await message.reply_text("The pending global match was cancelled. No coins were charged.")
        return
    if db_game.game_kind == GAME_KIND_CHESS:
        state.finish_with_resignation(user_id)
    else:
        losing_color = state.user_color(user_id)
        if losing_color is None:
            await message.reply_text("You are not a player in that game.")
            return
        state.finish_with_winner(losing_color.opponent, "resignation")
    await database.update_game_state(global_state_update(db_game, state, None))
    if await database.finish_game(FinishGame(db_game.id, state.winner_user_id(), state.result_reason)):
        await finish_global_game(database, db_game, state)
    await edit_global_game_messages(context.bot, database, db_game, state)
    await message.reply_text("You resigned from the active global game.")


async def handle_resume_global(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return
    if chat.type != ChatType.PRIVATE:
        await message.reply_text("Global games can be restored only in private chat with the bot.")
        return
    database = get_database(context)
    user_id = telegram_user_id(user)
    db_game = await database.get_active_global_game_for_user(user_id)
    if db_game is None:
        await message.reply_text("You have no active global game to restore.")
        return
    sent = await message.reply_text("Restoring your global game...")
    await database.create_game_view(GameView(db_game.id, user_id, sent.chat_id, sent.message_id))
    state = global_state_from_game(db_game)
    if state.status.value == "confirming":
        await edit_global_timeout_messages(context.bot, database, db_game, state)
    else:
        await edit_global_game_messages(context.bot, database, db_game, state)


async def handle_matchmaking_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if query.message.chat.type != ChatType.PRIVATE:
        await query.answer("Use random matchmaking in a private chat with the bot.", show_alert=True)
        return
    parsed = parse_matchmaking_callback(query.data)
    if parsed is None:
        await query.answer("That matchmaking action is no longer valid.")
        return
    action, game_kind, rated, anonymous = parsed
    if action == "cancel":
        await get_database(context).remove_matchmaking_entry(telegram_user_id(query.from_user))
        await query.answer("Queue cancelled.")
        await query.edit_message_text("Matchmaking cancelled.", reply_markup=config_keyboard())
        return
    if action == "cfg":
        await query.answer()
        await query.edit_message_text(
            config_text(game_kind, rated, anonymous),
            reply_markup=config_keyboard(game_kind, rated, anonymous),
        )
        return
    await join_matchmaking_queue(context, query, game_kind, rated, anonymous)


async def handle_global_timeout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    parsed = parse_global_timeout_callback(query.data)
    if parsed is None:
        await query.answer("That timeout action is no longer valid.")
        return
    game_id, action, seconds = parsed
    database = get_database(context)
    db_game = await database.get_game(game_id)
    if db_game is None:
        await query.answer("That global game no longer exists.")
        return
    state = global_state_from_game(db_game)
    user_id = telegram_user_id(query.from_user)
    if not state.global_game or user_id not in {state.black_user_id, state.white_user_id}:
        await query.answer("Only players in this global game can choose its timeout.", show_alert=True)
        return
    if state.status.value != "confirming":
        await query.answer("This game has already started.")
        return
    await query.answer()
    if action == "accept":
        await accept_global_timeout(context.bot, database, db_game, state, user_id)
    elif action == "change":
        await request_global_timeout_change(context.bot, database, db_game, state, user_id)
    elif action == "propose" and seconds is not None:
        await propose_global_timeout(context.bot, database, db_game, state, user_id, seconds)
    elif action == "cancel":
        await cancel_global_timeout(context.bot, database, db_game, state)


async def accept_global_timeout(bot, database: Database, db_game, state, user_id: int) -> bool:
    players = {state.black_user_id, state.white_user_id}
    accepted = set(state.timeout_accepted_user_ids)
    if state.timeout_stage == "default":
        accepted.add(user_id)
    elif state.timeout_stage == "proposal":
        if user_id == state.timeout_proposer_user_id:
            return False
        accepted.add(user_id)
    else:
        return False
    state.timeout_accepted_user_ids = sorted(accepted)
    if players.issubset(accepted):
        return await start_global_game(bot, database, db_game, state)
    await save_global_timeout_state(database, db_game, state)
    await edit_global_timeout_messages(bot, database, db_game, state)
    return False


async def request_global_timeout_change(bot, database: Database, db_game, state, user_id: int) -> bool:
    if state.timeout_stage != "default":
        return False
    state.timeout_stage = "choosing"
    state.timeout_proposer_user_id = user_id
    state.timeout_accepted_user_ids = []
    await save_global_timeout_state(database, db_game, state)
    await edit_global_timeout_messages(bot, database, db_game, state)
    return True


async def propose_global_timeout(
    bot,
    database: Database,
    db_game,
    state,
    user_id: int,
    seconds: int,
) -> bool:
    if (
        state.timeout_stage != "choosing"
        or state.timeout_proposer_user_id != user_id
        or seconds not in MOVE_TIMEOUT_OPTIONS
    ):
        return False
    state.move_timeout_seconds = seconds
    state.timeout_stage = "proposal"
    state.timeout_accepted_user_ids = [user_id]
    await save_global_timeout_state(database, db_game, state)
    await edit_global_timeout_messages(bot, database, db_game, state)
    return True


async def start_global_game(bot, database: Database, db_game, state) -> bool:
    if db_game.rated:
        charge_result = await charge_pvp_entry_fee_once(database, db_game, state, db_game.game_kind)
        if not charge_result.success:
            state.status = ChessStatus.FINISHED if db_game.game_kind == GAME_KIND_CHESS else GameStatus.FINISHED
            state.result_reason = "insufficient balance"
            await database.update_game_state(global_state_update(db_game, state, None))
            await database.finish_game(FinishGame(db_game.id, None, state.result_reason))
            await edit_game_views_text(
                bot,
                database,
                db_game.id,
                "The match was cancelled because a player could not pay the entry fee.",
            )
            return False
    state.status = ChessStatus.IN_PROGRESS if db_game.game_kind == GAME_KIND_CHESS else GameStatus.IN_PROGRESS
    state.timeout_stage = None
    state.timeout_proposer_user_id = None
    state.timeout_accepted_user_ids = []
    state.turn_started_at = now_text()
    await database.update_game_state(global_state_update(db_game, state, state.current_user_id()))
    await edit_global_game_messages(bot, database, db_game, state)
    return True


async def save_global_timeout_state(database: Database, db_game, state) -> None:
    await database.update_game_state(global_state_update(db_game, state, None))


async def cancel_global_timeout(
    bot,
    database: Database,
    db_game,
    state,
    *,
    reason: str = "timeout agreement cancelled",
    message_text: str = "The match was cancelled before the timeout was agreed. No coins were charged.",
) -> None:
    state.status = ChessStatus.FINISHED if db_game.game_kind == GAME_KIND_CHESS else GameStatus.FINISHED
    state.result_reason = reason
    await database.update_game_state(global_state_update(db_game, state, None))
    await database.finish_game(FinishGame(db_game.id, None, state.result_reason))
    await edit_game_views_text(bot, database, db_game.id, message_text)


async def join_matchmaking_queue(
    context,
    query: CallbackQuery,
    game_kind: str,
    rated: bool,
    anonymous: bool,
) -> None:
    database = get_database(context)
    user_id = telegram_user_id(query.from_user)
    await database.upsert_user(upsert_user_from_telegram(query.from_user))
    await database.upsert_chat(upsert_chat_from_telegram(query.message.chat))
    if await database.get_active_global_game_for_user(user_id) is not None:
        await query.answer("Finish your current global game first.", show_alert=True)
        return
    stats = await database.ensure_global_user_stats(user_id, game_kind)
    wallet = await database.ensure_global_wallet(user_id)
    own_rank = rank_for_rating(stats.rating)
    estimated_cost = rank_game_cost(own_rank, game_kind)
    if rated and wallet.kyzma_coin_balance < estimated_cost:
        await query.answer(
            f"You need at least {estimated_cost} kyzma-coins to enter this rated queue.",
            show_alert=True,
        )
        return
    entry = MatchmakingEntry(
        user_id=user_id,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        game_kind=game_kind,
        rated=rated,
        anonymous=anonymous,
        rating=stats.rating,
        joined_at=now_text(),
    )
    await database.add_matchmaking_entry(entry)
    await query.answer("Searching for an opponent...")
    await query.edit_message_text(queue_text(entry), reply_markup=queue_keyboard())
    await try_match_user(context.bot, database, user_id)


async def process_matchmaking_queue(context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    await expire_stale_matchmaking_entries(context.bot, database)
    for user_id in await database.list_matchmaking_user_ids():
        await try_match_user(context.bot, database, user_id)


async def process_global_game_timeouts(context: ContextTypes.DEFAULT_TYPE) -> None:
    database = get_database(context)
    await expire_stale_timeout_setups(context.bot, database)
    await expire_overdue_global_games(context.bot, database)


async def expire_stale_matchmaking_entries(
    bot,
    database: Database,
    now: datetime | None = None,
) -> list[int]:
    now = now or datetime.now(UTC)
    expired = await database.remove_expired_matchmaking_entries((now - MATCHMAKING_QUEUE_LIFETIME).isoformat())
    for entry in expired:
        await safe_edit_message(
            bot,
            entry.chat_id,
            entry.message_id,
            "Matchmaking expired after 30 minutes. Join again when you are ready.",
            config_keyboard(entry.game_kind, entry.rated, entry.anonymous),
        )
    return [entry.user_id for entry in expired]


async def expire_stale_timeout_setups(
    bot,
    database: Database,
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now(UTC)
    expired_game_ids: list[str] = []
    for db_game in await database.get_confirming_global_games():
        created_at = datetime.fromisoformat(db_game.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if now - created_at < TIMEOUT_SETUP_LIFETIME:
            continue
        state = global_state_from_game(db_game)
        await cancel_global_timeout(
            bot,
            database,
            db_game,
            state,
            reason="timeout setup expired",
            message_text="The match expired because its move timeout was not agreed within 5 minutes. No coins were charged.",
        )
        expired_game_ids.append(db_game.id)
    return expired_game_ids


async def expire_overdue_global_games(
    bot,
    database: Database,
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now(UTC)
    expired_game_ids: list[str] = []
    for db_game in await database.get_active_global_games():
        state = global_state_from_game(db_game)
        if not state.global_game:
            continue
        if state.move_timeout_seconds is None:
            state.move_timeout_seconds = default_move_timeout(db_game.game_kind)
        if state.turn_started_at is None:
            state.turn_started_at = now.isoformat()
            await database.update_game_state(global_state_update(db_game, state, state.current_user_id()))
            continue
        turn_started_at = datetime.fromisoformat(state.turn_started_at)
        if turn_started_at.tzinfo is None:
            turn_started_at = turn_started_at.replace(tzinfo=UTC)
        if (now - turn_started_at).total_seconds() < state.move_timeout_seconds:
            continue
        losing_user_id = state.current_user_id()
        if db_game.game_kind == GAME_KIND_CHESS:
            state.finish_with_resignation(losing_user_id)
            state.result_reason = "move timeout"
        else:
            losing_color = state.user_color(losing_user_id)
            if losing_color is None:
                continue
            state.finish_with_winner(losing_color.opponent, "move timeout")
        await database.update_game_state(global_state_update(db_game, state, None))
        if not await database.finish_game(FinishGame(db_game.id, state.winner_user_id(), state.result_reason)):
            continue
        await finish_global_game(database, db_game, state)
        await edit_global_game_messages(bot, database, db_game, state)
        expired_game_ids.append(db_game.id)
    return expired_game_ids


async def try_match_user(bot, database: Database, user_id: int) -> None:
    pair = await database.claim_matchmaking_pair(user_id)
    if pair is None:
        return
    await create_global_match(bot, database, pair[0], pair[1])


async def create_global_match(bot, database: Database, left: MatchmakingEntry, right: MatchmakingEntry) -> None:
    entries = [left, right]
    random.shuffle(entries)
    white_entry, black_entry = entries
    rank, cost = match_rank_and_cost(left.rating, right.rating, left.game_kind)
    if left.rated:
        insufficient = await database.get_insufficient_kyzma_user_ids(
            GLOBAL_CHAT_ID,
            (left.user_id, right.user_id),
            left.game_kind,
            cost,
        )
        if insufficient:
            await restore_match_after_insufficient_balance(bot, database, entries, insufficient, cost)
            return
    if not await prepare_match_messages(bot, database, entries):
        return

    await database.upsert_chat(UpsertChat(GLOBAL_CHAT_ID, "Global matchmaking", "global"))
    if left.game_kind == GAME_KIND_CHESS:
        state = ChessState.new(white_entry.user_id, black_entry.user_id)
    else:
        state = DraughtsState.new(black_entry.user_id, white_entry.user_id)
    state.global_game = True
    state.global_rank = rank.name if left.rated else None
    state.anonymous_user_ids = sorted(entry.user_id for entry in entries if entry.anonymous)
    state.move_timeout_seconds = default_move_timeout(left.game_kind)
    state.timeout_stage = "default"
    state.timeout_accepted_user_ids = []
    state.status = ChessStatus.CONFIRMING if left.game_kind == GAME_KIND_CHESS else GameStatus.CONFIRMING
    if left.rated:
        set_kyzma_prize(
            state,
            cost,
            prize_multiplier_factor=CHESS_PRIZE_MULTIPLIER_FACTOR if left.game_kind == GAME_KIND_CHESS else 1,
        )
    db_game = await database.create_game(NewGame(
        chat_id=GLOBAL_CHAT_ID,
        message_id=None,
        inline_message_id=None,
        game_kind=left.game_kind,
        status=state.status.value,
        rated=left.rated,
        state=state,
        current_turn_user_id=None,
        black_user_id=black_entry.user_id,
        white_user_id=white_entry.user_id,
    ))
    for entry in entries:
        await database.create_game_view(GameView(db_game.id, entry.user_id, entry.chat_id, entry.message_id))
    await edit_global_timeout_messages(bot, database, db_game, state)


async def prepare_match_messages(bot, database: Database, entries: list[MatchmakingEntry]) -> bool:
    prepared: list[MatchmakingEntry] = []
    for entry in entries:
        try:
            await bot.edit_message_text(
                chat_id=entry.chat_id,
                message_id=entry.message_id,
                text="Opponent found. Preparing the game...",
            )
            prepared.append(entry)
        except (BadRequest, Forbidden):
            logger.warning("global queue message is unavailable", extra={"user_id": entry.user_id})
            for recoverable in prepared:
                await database.add_matchmaking_entry(recoverable)
                try:
                    await bot.edit_message_text(
                        chat_id=recoverable.chat_id,
                        message_id=recoverable.message_id,
                        text=queue_text(recoverable),
                        reply_markup=queue_keyboard(),
                    )
                except (BadRequest, Forbidden):
                    logger.warning("failed to restore global queue message", extra={"user_id": recoverable.user_id})
            for waiting in entries:
                if waiting not in prepared and waiting.user_id != entry.user_id:
                    await database.add_matchmaking_entry(waiting)
            return False
    return True


async def restore_match_after_insufficient_balance(
    bot,
    database: Database,
    entries: list[MatchmakingEntry],
    insufficient_user_ids: tuple[int, ...],
    cost: int,
) -> None:
    insufficient = set(insufficient_user_ids)
    for entry in entries:
        if entry.user_id in insufficient:
            try:
                await bot.edit_message_text(
                    chat_id=entry.chat_id,
                    message_id=entry.message_id,
                    text=f"Match found, but you need {cost} kyzma-coins for its rank.",
                    reply_markup=config_keyboard(entry.game_kind, entry.rated, entry.anonymous),
                )
            except (BadRequest, Forbidden):
                logger.exception("failed to report insufficient global matchmaking balance")
        else:
            await database.add_matchmaking_entry(entry)


async def edit_global_timeout_messages(bot, database: Database, db_game, state) -> None:
    white = await database.get_user(state.white_user_id)
    black = await database.get_user(state.black_user_id)
    white_name = global_player_name(white, state.anonymous_user_ids)
    black_name = global_player_name(black, state.anonymous_user_ids)
    accepted = set(state.timeout_accepted_user_ids)
    for view in await database.get_game_views(db_game.id):
        text = timeout_setup_text(
            db_game,
            state,
            white_name,
            black_name,
            view.user_id,
        )
        keyboard = timeout_setup_keyboard(db_game.id, state, view.user_id, accepted)
        try:
            await bot.edit_message_text(
                chat_id=view.chat_id,
                message_id=view.message_id,
                text=text,
                reply_markup=keyboard,
            )
        except BadRequest as error:
            if "message is not modified" not in str(error).lower():
                logger.exception("failed to update global timeout setup", extra={"game_id": db_game.id, "user_id": view.user_id})
        except Forbidden:
            logger.warning("player blocked the bot during timeout setup", extra={"game_id": db_game.id, "user_id": view.user_id})


def timeout_setup_text(db_game, state, white_name: str, black_name: str, viewer_user_id: int) -> str:
    lines = [
        "Global match found · Timeout setup",
        f"Game: {db_game.game_kind.title()} · {'Rated' if db_game.rated else 'Unrated'}",
        f"White: {white_name}",
        f"Black: {black_name}",
    ]
    if db_game.rated and state.global_rank:
        lines.extend([
            f"Rank: {state.global_rank}",
            f"Game cost: {state.kyzma_prize_base} kyzma-coins",
        ])
    timeout = format_timeout(state.move_timeout_seconds or default_move_timeout(db_game.game_kind))
    if state.timeout_stage == "default":
        lines.extend([
            f"Default move timeout: {timeout}",
            f"Accepted: {len(set(state.timeout_accepted_user_ids))}/2",
            "Both players must accept, or one player can propose another timeout.",
        ])
    elif state.timeout_stage == "choosing":
        if viewer_user_id == state.timeout_proposer_user_id:
            lines.append("Choose how much time each player should have for every move.")
        else:
            lines.append("Your opponent is choosing another move timeout.")
    elif state.timeout_stage == "proposal":
        lines.append(f"Proposed move timeout: {timeout}")
        if viewer_user_id == state.timeout_proposer_user_id:
            lines.append("Waiting for your opponent to accept your proposal.")
        else:
            lines.append("Accept the proposed timeout to start the game.")
    return "\n".join(lines)


def timeout_setup_keyboard(game_id: str, state, viewer_user_id: int, accepted: set[int]) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if state.timeout_stage == "default":
        if viewer_user_id not in accepted:
            rows.append([
                InlineKeyboardButton("Accept default", callback_data=f"gmt:{game_id}:accept"),
                InlineKeyboardButton("Choose another", callback_data=f"gmt:{game_id}:change"),
            ])
    if state.timeout_stage == "choosing" and viewer_user_id == state.timeout_proposer_user_id:
        buttons = [
            InlineKeyboardButton(format_timeout(seconds), callback_data=f"gmt:{game_id}:propose:{seconds}")
            for seconds in MOVE_TIMEOUT_OPTIONS
        ]
        rows.extend([buttons[:3], buttons[3:]])
    if state.timeout_stage == "proposal" and viewer_user_id != state.timeout_proposer_user_id:
        rows.append([
            InlineKeyboardButton("Accept timeout", callback_data=f"gmt:{game_id}:accept")
        ])
    rows.append([InlineKeyboardButton("Cancel match", callback_data=f"gmt:{game_id}:cancel")])
    return InlineKeyboardMarkup(rows)


async def edit_global_game_messages(bot, database: Database, db_game, state) -> None:
    white = await database.get_user(state.white_user_id)
    black = await database.get_user(state.black_user_id)
    white_name = global_player_name(white, state.anonymous_user_ids)
    black_name = global_player_name(black, state.anonymous_user_ids)
    if db_game.game_kind == GAME_KIND_CHESS:
        text = render_chess_message(state, white_name, black_name, db_game.rated, Lang.EN)
        keyboard = render_chess_keyboard(db_game.id, state, Lang.EN)
    else:
        text = render_draughts_message(state, black_name, white_name, db_game.rated, Lang.EN)
        keyboard = render_draughts_keyboard(db_game.id, state, Lang.EN)
    prefix = "Global match"
    if db_game.rated and state.global_rank:
        prefix += f" · {state.global_rank}\nGame cost: {state.kyzma_prize_base} kyzma-coins"
    if state.move_timeout_seconds:
        prefix += f"\nMove timeout: {format_timeout(state.move_timeout_seconds)}"
    text = f"{prefix}\n\n{text}"
    for view in await database.get_game_views(db_game.id):
        try:
            await bot.edit_message_text(
                chat_id=view.chat_id,
                message_id=view.message_id,
                text=text,
                reply_markup=keyboard,
            )
        except BadRequest as error:
            if "message is not modified" not in str(error).lower():
                logger.exception("failed to synchronize global game view", extra={"game_id": db_game.id, "user_id": view.user_id})
        except Forbidden:
            logger.warning("player blocked the bot during a global game", extra={"game_id": db_game.id, "user_id": view.user_id})


async def edit_game_views_text(bot, database: Database, game_id: str, text: str) -> None:
    for view in await database.get_game_views(game_id):
        try:
            await bot.edit_message_text(chat_id=view.chat_id, message_id=view.message_id, text=text)
        except (BadRequest, Forbidden):
            logger.exception("failed to edit global game view", extra={"game_id": game_id, "user_id": view.user_id})


async def safe_edit_message(
    bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
        return True
    except BadRequest as error:
        if "message is not modified" not in str(error).lower():
            logger.warning(
                "message is unavailable for editing",
                extra={"chat_id": chat_id, "message_id": message_id, "error": str(error)},
            )
    except Forbidden:
        logger.warning("bot cannot edit a player's message", extra={"chat_id": chat_id, "message_id": message_id})
    return False


async def finish_global_game(database: Database, db_game, state) -> None:
    if db_game.rated:
        await database.update_global_stats_after_game(GameOutcome(
            chat_id=GLOBAL_CHAT_ID,
            game_kind=db_game.game_kind,
            black_user_id=db_game.black_user_id,
            white_user_id=db_game.white_user_id,
            winner_user_id=state.winner_user_id(),
        ))
    await award_finished_game_currency(database, db_game, state, db_game.game_kind)


async def send_global_game_stats(context, database: Database, query: CallbackQuery, game_kind: str, reply_to_message_id: int | None) -> None:
    user_id = telegram_user_id(query.from_user)
    stats = await database.ensure_global_user_stats(user_id, game_kind)
    wallet = await database.ensure_global_wallet(user_id)
    await query.answer()
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=global_game_stats_text(game_kind, stats, wallet.kyzma_coin_balance, stats_display_name(query.from_user)),
        reply_parameters=ReplyParameters(message_id=reply_to_message_id) if reply_to_message_id else None,
    )


def global_player_name(user, anonymous_user_ids: list[int]) -> str:
    if user.telegram_user_id in anonymous_user_ids:
        return "Anonymous"
    return display_name_from_db_user(user)


def config_text(game_kind: str = GAME_KIND_DRAUGHTS, rated: bool = True, anonymous: bool = False) -> str:
    stats_mode = "Rated" if rated else "Unrated"
    identity = "Anonymous" if anonymous else "Show my name"
    return (
        "Random opponent\n\n"
        f"Game: {game_kind.title()}\n"
        f"Mode: {stats_mode}\n"
        f"Identity: {identity}\n\n"
        "Global games are played in English. Rated matches affect global rating and charge rank-based entry fees."
    )


def config_keyboard(
    game_kind: str = GAME_KIND_DRAUGHTS,
    rated: bool = True,
    anonymous: bool = False,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(mark_selected("Draughts", game_kind == GAME_KIND_DRAUGHTS), callback_data=mm_data("cfg", GAME_KIND_DRAUGHTS, rated, anonymous)),
            InlineKeyboardButton(mark_selected("Chess", game_kind == GAME_KIND_CHESS), callback_data=mm_data("cfg", GAME_KIND_CHESS, rated, anonymous)),
        ],
        [
            InlineKeyboardButton(mark_selected("Rated", rated), callback_data=mm_data("cfg", game_kind, True, anonymous)),
            InlineKeyboardButton(mark_selected("Unrated", not rated), callback_data=mm_data("cfg", game_kind, False, anonymous)),
        ],
        [
            InlineKeyboardButton(mark_selected("Show name", not anonymous), callback_data=mm_data("cfg", game_kind, rated, False)),
            InlineKeyboardButton(mark_selected("Anonymous", anonymous), callback_data=mm_data("cfg", game_kind, rated, True)),
        ],
        [InlineKeyboardButton("Join queue", callback_data=mm_data("join", game_kind, rated, anonymous))],
    ])


def queue_text(entry: MatchmakingEntry) -> str:
    mode = "Rated" if entry.rated else "Unrated"
    identity = "Anonymous" if entry.anonymous else "Name visible"
    lines = [
        "Searching for a random opponent...",
        f"Game: {entry.game_kind.title()}",
        f"Mode: {mode}",
        f"Identity: {identity}",
    ]
    if entry.rated:
        rank = rank_for_rating(entry.rating)
        lines.extend([
            f"Global rating: {entry.rating} ({rank.name})",
            f"Current-rank cost: {rank_game_cost(rank, entry.game_kind)} kyzma-coins",
            "The search range widens while you wait.",
        ])
    return "\n".join(lines)


def queue_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Cancel search", callback_data="mm:cancel")]])


def global_stats_summary(draughts, chess, balance: int) -> str:
    draughts_rank = rank_for_rating(draughts.rating)
    chess_rank = rank_for_rating(chess.rating)
    return "\n".join([
        "Global profile",
        f"Wallet: {balance} kyzma-coins",
        "",
        f"Draughts: {draughts.rating} · {draughts_rank.name}",
        f"Games: {draughts.games_played} · Wins: {draughts.wins} · Losses: {draughts.losses} · Draws: {draughts.draws}",
        f"Rated cost: {rank_game_cost(draughts_rank, GAME_KIND_DRAUGHTS)} kyzma-coins",
        "",
        f"Chess: {chess.rating} · {chess_rank.name}",
        f"Games: {chess.games_played} · Wins: {chess.wins} · Losses: {chess.losses} · Draws: {chess.draws}",
        f"Rated cost: {rank_game_cost(chess_rank, GAME_KIND_CHESS)} kyzma-coins",
    ])


def global_game_stats_text(game_kind: str, stats, balance: int, player_name: str) -> str:
    rank = rank_for_rating(stats.rating)
    return "\n".join([
        f"Global {game_kind.title()} stats",
        f"Player: {player_name}",
        f"Games: {stats.games_played}",
        f"Wins: {stats.wins}",
        f"Losses: {stats.losses}",
        f"Draws: {stats.draws}",
        f"Rating: {stats.rating}",
        f"Rank: {rank.name}",
        f"Rated game cost: {rank_game_cost(rank, game_kind)} kyzma-coins",
        f"Wallet: {balance} kyzma-coins",
        f"Current streak: {stats.current_streak}",
        f"Best streak: {stats.best_streak}",
    ])


def default_move_timeout(game_kind: str) -> int:
    return DEFAULT_MOVE_TIMEOUTS.get(game_kind, DEFAULT_MOVE_TIMEOUTS[GAME_KIND_DRAUGHTS])


def format_timeout(seconds: int) -> str:
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    return f"{seconds} seconds"


def global_state_from_game(db_game):
    if db_game.game_kind == GAME_KIND_CHESS:
        return ChessState.from_json(db_game.state)
    return DraughtsState.from_json(db_game.state)


def global_state_update(db_game, state, current_turn_user_id: int | None) -> GameStateUpdate:
    return GameStateUpdate(
        game_id=db_game.id,
        message_id=None,
        status=state.status.value,
        state=state,
        current_turn_user_id=current_turn_user_id,
    )


def parse_global_timeout_callback(data: str) -> tuple[str, str, int | None] | None:
    parts = data.split(":")
    if len(parts) == 3 and parts[0] == "gmt" and parts[2] in {"accept", "change", "cancel"}:
        return parts[1], parts[2], None
    if len(parts) == 4 and parts[0] == "gmt" and parts[2] == "propose":
        try:
            seconds = int(parts[3])
        except ValueError:
            return None
        if seconds in MOVE_TIMEOUT_OPTIONS:
            return parts[1], "propose", seconds
    return None


def mm_data(action: str, game_kind: str, rated: bool, anonymous: bool) -> str:
    return f"mm:{action}:{game_kind}:{'rated' if rated else 'unrated'}:{'anon' if anonymous else 'name'}"


def parse_matchmaking_callback(data: str) -> tuple[str, str, bool, bool] | None:
    if data == "mm:cancel":
        return "cancel", GAME_KIND_DRAUGHTS, True, False
    parts = data.split(":")
    if len(parts) != 5 or parts[0] != "mm" or parts[1] not in {"cfg", "join"}:
        return None
    if parts[2] not in {GAME_KIND_DRAUGHTS, GAME_KIND_CHESS}:
        return None
    if parts[3] not in {"rated", "unrated"} or parts[4] not in {"anon", "name"}:
        return None
    return parts[1], parts[2], parts[3] == "rated", parts[4] == "anon"


def mark_selected(label: str, selected: bool) -> str:
    return f"✓ {label}" if selected else label
