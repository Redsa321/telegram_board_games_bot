from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, replace

import chess
from telegram import CallbackQuery, ReplyParameters, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import i18n
from .commands import (
    GAME_KIND_CHESS,
    create_chess_game_message,
    create_chess_robot_game_message,
    display_name_from_db_user,
    get_database,
    render_stats_text,
    status_text,
    telegram_user_id,
    upsert_user_from_telegram,
)
from .db import Database, FinishGame, GameOutcome, GameStateUpdate, NewGame, NewMove, now_text
from .economy import (
    CHESS_PRIZE_MULTIPLIER_FACTOR,
    CHESS_PVP_COST_MULTIPLIER,
    award_finished_game_currency,
    charge_pvp_entry_fee_once,
    configure_pvp_prize,
    pvp_players_without_entry_fee,
)
from .games.chess_game import ChessState, ChessStatus, valid_square_name
from .games.chess_robot import choose_chess_robot_move
from .games.robot import RobotDifficulty, parse_difficulty
from .global_matchmaking import edit_global_game_messages, finish_global_game, send_global_game_stats
from .i18n import Lang
from .render.chess_board import (
    render_chess_confirmation_keyboard,
    render_chess_confirmation_message,
    render_chess_keyboard,
    render_chess_message,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageTarget:
    chat_id: int | None = None
    message_id: int | None = None
    inline_message_id: str | None = None


@dataclass(frozen=True)
class ParsedChessCallback:
    game_id: str
    action: str
    value: str | None = None
    selection: str | None = None

    @classmethod
    def parse(cls, data: str) -> "ParsedChessCallback | None":
        parts = data.split(":", 3)
        if len(parts) < 3 or parts[0] != "ch":
            return None
        game_id = parts[1]
        action = parts[2]
        value = parts[3] if len(parts) == 4 else None
        if game_id == "robot" and (difficulty := parse_difficulty(action)) is not None:
            return cls(game_id, "robot", difficulty.value)
        if action == "sq" and value:
            square_name, _, selection = value.partition(":")
            if not valid_square_name(square_name):
                return None
            if selection and selection != "__" and not valid_square_name(selection):
                return None
            return cls(game_id, action, square_name, selection or None)
        if action == "promo" and value in {"q", "r", "b", "n"}:
            return cls(game_id, action, value)
        if action in {"join", "joinu", "accept", "resign", "stats", "pad"}:
            return cls(game_id, action)
        return None


class InsufficientKyzmaCoins(Exception):
    def __init__(self, cost: int, user_ids: tuple[int, ...]):
        super().__init__("not enough kyzma-coins")
        self.cost = cost
        self.user_ids = user_ids


async def handle_chess_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    lang = i18n.user_lang(query.from_user)
    try:
        await dispatch_chess_callback(query, context)
    except Exception:
        await query.answer(i18n.generic_error(lang), show_alert=False)
        raise


async def dispatch_chess_callback(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = i18n.user_lang(query.from_user)
    if query.data is None:
        await query.answer(i18n.button_no_action(lang))
        return
    parsed = ParsedChessCallback.parse(query.data)
    if parsed is None:
        await query.answer(i18n.unrecognized_action(lang))
        return
    if query.inline_message_id:
        target = MessageTarget(inline_message_id=query.inline_message_id)
    elif query.message:
        target = MessageTarget(chat_id=query.message.chat_id, message_id=query.message.message_id)
    else:
        await query.answer(i18n.button_no_context(lang))
        return

    database = get_database(context)
    if parsed.action in {"join", "joinu"}:
        if target.chat_id is None or target.message_id is None:
            await query.answer(i18n.post_new_invite_to_join(lang))
            return
        await handle_chess_join_callback(context, database, query, target, parsed.game_id, parsed.action == "join")
    elif parsed.action == "accept":
        await handle_chess_accept_callback(context, database, query, target, parsed.game_id)
    elif parsed.action == "robot" and parsed.value is not None:
        await handle_chess_robot_start_callback(context, database, query, target, parsed.value)
    elif parsed.action == "sq" and parsed.value is not None:
        await handle_chess_square_callback(
            context,
            database,
            query,
            target,
            parsed.game_id,
            parsed.value,
            parsed.selection if parsed.selection and parsed.selection != "__" else None,
        )
    elif parsed.action == "promo" and parsed.value is not None:
        await handle_chess_promotion_callback(context, database, query, target, parsed.game_id, parsed.value)
    elif parsed.action == "resign":
        await handle_chess_resign_callback(context, database, query, target, parsed.game_id)
    elif parsed.action == "stats":
        await handle_chess_stats_callback(context, database, query, target.chat_id, target.message_id, parsed.game_id)
    else:
        await query.answer()


async def handle_chess_join_callback(
    context,
    database: Database,
    query: CallbackQuery,
    target: MessageTarget,
    challenger_id_text: str,
    rated: bool,
) -> None:
    lang = i18n.user_lang(query.from_user)
    if query.from_user.is_bot:
        await query.answer(i18n.bots_cannot_join_chess(lang))
        return
    try:
        challenger_id = int(challenger_id_text)
    except ValueError:
        await query.answer(i18n.invite_invalid_create(lang))
        return
    joiner_id = telegram_user_id(query.from_user)
    if joiner_id == challenger_id:
        await query.answer(i18n.cannot_join_own_invite(lang))
        return
    if await database.get_active_game_by_message(target.chat_id, target.message_id):
        await query.answer(i18n.invite_already_started(lang))
        return
    try:
        await database.get_user(challenger_id)
    except LookupError:
        await query.answer(i18n.invite_expired_create(lang))
        return
    await database.upsert_user(upsert_user_from_telegram(query.from_user))
    try:
        if rated:
            await create_chess_confirmation_message(context, database, target, challenger_id, joiner_id)
        else:
            await create_chess_game_message(
                context.bot,
                database,
                target.chat_id,
                target.message_id,
                joiner_id,
                challenger_id,
                False,
            )
    except sqlite3.IntegrityError:
        logger.info("chess join ignored: active game already exists on message", extra={"chat_id": target.chat_id, "message_id": target.message_id})
        await query.answer(i18n.invite_already_started(lang))
        return
    except InsufficientKyzmaCoins as exc:
        await query.answer(i18n.not_enough_kyzma_coins(lang, exc.cost), show_alert=True)
        return
    await query.answer()


async def create_chess_confirmation_message(
    context,
    database: Database,
    target: MessageTarget,
    challenger_id: int,
    joiner_id: int,
):
    if target.chat_id is None or target.message_id is None:
        raise ValueError("rated chess confirmation requires a chat message target")
    state = ChessState.new(joiner_id, challenger_id)
    state.status = ChessStatus.CONFIRMING
    await configure_pvp_prize(
        database,
        target.chat_id,
        challenger_id,
        joiner_id,
        GAME_KIND_CHESS,
        state,
        cost_multiplier=CHESS_PVP_COST_MULTIPLIER,
        prize_multiplier_factor=CHESS_PRIZE_MULTIPLIER_FACTOR,
    )
    cost = state.kyzma_prize_base or 0
    insufficient_user_ids = await pvp_players_without_entry_fee(
        database,
        target.chat_id,
        challenger_id,
        joiner_id,
        GAME_KIND_CHESS,
        state,
    )
    if insufficient_user_ids:
        raise InsufficientKyzmaCoins(cost, insufficient_user_ids)
    db_game = await database.create_game(NewGame(
        chat_id=target.chat_id,
        message_id=target.message_id,
        inline_message_id=None,
        game_kind=GAME_KIND_CHESS,
        status=status_text(state),
        rated=True,
        state=state,
        current_turn_user_id=None,
        black_user_id=challenger_id,
        white_user_id=joiner_id,
    ))
    await edit_chess_confirmation_message(context, target, db_game.id, state, database)
    return db_game


async def handle_chess_accept_callback(context, database: Database, query: CallbackQuery, target: MessageTarget, game_id: str) -> None:
    lang = i18n.user_lang(query.from_user)
    db_game = await database.get_game(game_id)
    if db_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    if db_game.game_kind != GAME_KIND_CHESS:
        await query.answer(i18n.wrong_chess_game_kind(lang))
        return
    state = ChessState.from_json(db_game.state)
    if state.global_game:
        lang = Lang.EN
    if state.status is not ChessStatus.CONFIRMING:
        await query.answer(i18n.game_not_waiting_for_accept(lang))
        return
    user_id = telegram_user_id(query.from_user)
    if user_id not in {state.black_user_id, state.white_user_id}:
        await query.answer(i18n.only_players_can_accept(lang))
        return

    cost = state.kyzma_prize_base or 0
    insufficient_user_ids = await pvp_players_without_entry_fee(
        database,
        db_game.chat_id,
        db_game.black_user_id,
        db_game.white_user_id,
        GAME_KIND_CHESS,
        state,
    )
    if insufficient_user_ids:
        state.accepted_user_ids = [
            accepted_user_id
            for accepted_user_id in state.accepted_user_ids
            if accepted_user_id not in set(insufficient_user_ids)
        ]
        await database.update_game_state(GameStateUpdate(db_game.id, target.message_id, status_text(state), state, None))
        await edit_chess_confirmation_message(context, target, db_game.id, state, database)
        await query.answer(i18n.not_enough_kyzma_coins(lang, cost), show_alert=True)
        return

    accepted = set(state.accepted_user_ids)
    was_already_accepted = user_id in accepted
    accepted.add(user_id)
    state.accepted_user_ids = sorted(accepted)

    if {state.black_user_id, state.white_user_id}.issubset(accepted):
        charge_result = await charge_pvp_entry_fee_once(database, db_game, state, GAME_KIND_CHESS)
        if not charge_result.success:
            state.accepted_user_ids = [
                accepted_user_id
                for accepted_user_id in state.accepted_user_ids
                if accepted_user_id not in set(charge_result.insufficient_user_ids)
            ]
            await database.update_game_state(GameStateUpdate(db_game.id, target.message_id, status_text(state), state, None))
            await edit_chess_confirmation_message(context, target, db_game.id, state, database)
            await query.answer(i18n.not_enough_kyzma_coins(lang, cost), show_alert=True)
            return
        state.status = ChessStatus.IN_PROGRESS
        state.accepted_user_ids = []
        await database.update_game_state(GameStateUpdate(
            db_game.id,
            target.message_id,
            status_text(state),
            state,
            state.current_user_id(),
        ))
        await edit_chess_game_message(context, target, db_game.id, state, db_game.rated, database)
        await query.answer(i18n.game_started(lang))
        return

    await database.update_game_state(GameStateUpdate(db_game.id, target.message_id, status_text(state), state, None))
    await edit_chess_confirmation_message(context, target, db_game.id, state, database)
    await query.answer(i18n.game_accept_waiting(lang) if was_already_accepted else i18n.game_accept_recorded(lang))


async def handle_chess_robot_start_callback(
    context,
    database: Database,
    query: CallbackQuery,
    target: MessageTarget,
    difficulty_text: str,
) -> None:
    lang = i18n.user_lang(query.from_user)
    difficulty = parse_difficulty(difficulty_text)
    if difficulty is None:
        await query.answer(i18n.unrecognized_action(lang))
        return
    if target.chat_id is None or target.message_id is None:
        await query.answer(i18n.button_no_context(lang))
        return
    if await database.get_active_game_by_message(target.chat_id, target.message_id):
        await query.answer(i18n.invite_already_started(lang))
        return
    await query.answer()
    try:
        await create_chess_robot_game_message(
            context.bot,
            database,
            target.chat_id,
            target.message_id,
            query.from_user,
            difficulty,
        )
    except sqlite3.IntegrityError:
        logger.info("chess robot game start ignored: active game already exists on message", extra={"chat_id": target.chat_id, "message_id": target.message_id})


async def handle_chess_square_callback(
    context,
    database: Database,
    query: CallbackQuery,
    target: MessageTarget,
    game_id: str,
    square_name: str,
    callback_selected: str | None = None,
) -> None:
    lang = i18n.user_lang(query.from_user)
    db_game = await database.get_game(game_id)
    if db_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    if db_game.game_kind != GAME_KIND_CHESS:
        await query.answer(i18n.wrong_chess_game_kind(lang))
        return
    state = ChessState.from_json(db_game.state)
    if state.global_game:
        lang = Lang.EN
    if state.status is ChessStatus.CONFIRMING:
        await query.answer(i18n.game_not_started(lang))
        return
    if state.status is ChessStatus.FINISHED:
        await query.answer(i18n.game_already_over(lang))
        return
    user_id = telegram_user_id(query.from_user)
    if state.current_user_id() != user_id:
        await query.answer(i18n.not_your_turn(lang))
        return
    if state.promotion_from and state.promotion_to:
        await query.answer(i18n.promote_to(lang))
        return

    board = state.board()
    square = chess.parse_square(square_name)
    user_color = state.user_color(user_id)
    piece = board.piece_at(square)
    if piece is not None and piece.color == user_color:
        if not any(move.from_square == square for move in board.legal_moves):
            await query.answer(i18n.piece_no_legal_moves(lang))
            return
        state.select_square(square_name)
        await database.update_game_state(GameStateUpdate(db_game.id, target.message_id, status_text(state), state, state.current_user_id()))
        await query.answer()
        await edit_chess_game_message(context, target, db_game.id, state, db_game.rated, database)
        return

    from_square_name = state.selected_square or callback_selected
    if from_square_name is None:
        if piece is not None:
            await query.answer(i18n.opponents_piece(lang))
        else:
            await query.answer()
        return

    promotion_options = state.promotion_options(from_square_name, square_name)
    if promotion_options:
        state.set_promotion_pending(from_square_name, square_name)
        await database.update_game_state(GameStateUpdate(db_game.id, target.message_id, status_text(state), state, state.current_user_id()))
        await query.answer()
        await edit_chess_game_message(context, target, db_game.id, state, db_game.rated, database)
        return

    move = state.legal_move(from_square_name, square_name)
    if move is None:
        await query.answer(i18n.move_illegal(lang))
        return
    await query.answer()
    await play_chess_move_and_update(context, database, target, db_game, state, move, user_id)


async def handle_chess_promotion_callback(
    context,
    database: Database,
    query: CallbackQuery,
    target: MessageTarget,
    game_id: str,
    promotion_token: str,
) -> None:
    lang = i18n.user_lang(query.from_user)
    db_game = await database.get_game(game_id)
    if db_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    if db_game.game_kind != GAME_KIND_CHESS:
        await query.answer(i18n.wrong_chess_game_kind(lang))
        return
    state = ChessState.from_json(db_game.state)
    if state.global_game:
        lang = Lang.EN
    if state.status is not ChessStatus.IN_PROGRESS:
        await query.answer(i18n.game_already_over(lang) if state.status is ChessStatus.FINISHED else i18n.game_not_started(lang))
        return
    user_id = telegram_user_id(query.from_user)
    if state.current_user_id() != user_id:
        await query.answer(i18n.not_your_turn(lang))
        return
    if not state.promotion_from or not state.promotion_to:
        await query.answer(i18n.move_unavailable(lang))
        return
    promotion = {"q": chess.QUEEN, "r": chess.ROOK, "b": chess.BISHOP, "n": chess.KNIGHT}[promotion_token]
    move = state.legal_move(state.promotion_from, state.promotion_to, promotion)
    if move is None:
        await query.answer(i18n.move_illegal(lang))
        return
    await query.answer()
    await play_chess_move_and_update(context, database, target, db_game, state, move, user_id)


async def handle_chess_resign_callback(context, database: Database, query: CallbackQuery, target: MessageTarget, game_id: str) -> None:
    lang = i18n.user_lang(query.from_user)
    db_game = await database.get_game(game_id)
    if db_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    if db_game.game_kind != GAME_KIND_CHESS:
        await query.answer(i18n.wrong_chess_game_kind(lang))
        return
    state = ChessState.from_json(db_game.state)
    if state.global_game:
        lang = Lang.EN
    if state.status is ChessStatus.CONFIRMING:
        await query.answer(i18n.game_not_started(lang))
        return
    if state.status is ChessStatus.FINISHED:
        await query.answer(i18n.game_already_over(lang))
        return
    user_id = telegram_user_id(query.from_user)
    if state.user_color(user_id) is None:
        await query.answer(i18n.only_player_can_resign(lang))
        return
    state.finish_with_resignation(user_id)
    await query.answer()
    await database.update_game_state(GameStateUpdate(db_game.id, target.message_id, status_text(state), state, None))
    await finish_chess_game(database, db_game, state)
    await edit_chess_game_message(context, target, db_game.id, state, db_game.rated, database)


async def handle_chess_stats_callback(
    context,
    database: Database,
    query: CallbackQuery,
    chat_id: int | None,
    reply_to_message_id: int | None,
    game_id: str,
) -> None:
    lang = i18n.user_lang(query.from_user)
    await database.upsert_user(upsert_user_from_telegram(query.from_user))
    if chat_id is None:
        await query.answer(i18n.stats_group_only(lang))
        return
    db_game = await database.get_game(game_id)
    if db_game is not None:
        state = ChessState.from_json(db_game.state)
        if state.global_game:
            await send_global_game_stats(context, database, query, GAME_KIND_CHESS, reply_to_message_id)
            return
    user_id = telegram_user_id(query.from_user)
    chess_stats = await database.ensure_user_stats(chat_id, user_id, GAME_KIND_CHESS)
    wallet = await database.ensure_global_wallet(user_id)
    stats = replace(chess_stats, kyzma_coin_balance=wallet.kyzma_coin_balance)
    reply_parameters = ReplyParameters(message_id=reply_to_message_id) if reply_to_message_id is not None else None
    await query.answer()
    await context.bot.send_message(
        chat_id=chat_id,
        text=render_stats_text(lang, stats, query.from_user, i18n.chess_game_name(lang)),
        parse_mode=ParseMode.HTML,
        reply_parameters=reply_parameters,
    )


async def play_chess_move_and_update(
    context,
    database: Database,
    target: MessageTarget,
    db_game,
    state: ChessState,
    move: chess.Move,
    user_id: int,
) -> None:
    board = state.board()
    move_number = board.fullmove_number
    move_text = board.san(move)
    state.apply_move(move)
    if state.global_game and state.status is ChessStatus.IN_PROGRESS:
        state.turn_started_at = now_text()
    await database.insert_move(NewMove(
        game_id=db_game.id,
        move_number=move_number,
        user_id=user_id,
        move_text=move_text,
        state_after=state,
    ))
    for robot_move_number, robot_user_id, robot_move_text, robot_state_after in apply_chess_robot_turn(state):
        await database.insert_move(NewMove(
            game_id=db_game.id,
            move_number=robot_move_number,
            user_id=robot_user_id,
            move_text=robot_move_text,
            state_after=robot_state_after,
        ))
    await database.update_game_state(GameStateUpdate(
        game_id=db_game.id,
        message_id=target.message_id,
        status=status_text(state),
        state=state,
        current_turn_user_id=None if state.status is ChessStatus.FINISHED else state.current_user_id(),
    ))
    if state.status is ChessStatus.FINISHED:
        await finish_chess_game(database, db_game, state)
    await edit_chess_game_message(context, target, db_game.id, state, db_game.rated, database)


async def finish_chess_game(database: Database, db_game, state: ChessState) -> None:
    if not await database.finish_game(FinishGame(db_game.id, state.winner_user_id(), state.result_reason)):
        return
    if state.global_game:
        await finish_global_game(database, db_game, state)
        return
    if db_game.rated:
        await database.update_stats_after_game(GameOutcome(
            chat_id=db_game.chat_id,
            game_kind=GAME_KIND_CHESS,
            black_user_id=db_game.black_user_id,
            white_user_id=db_game.white_user_id,
            winner_user_id=state.winner_user_id(),
        ))
    await award_finished_game_currency(database, db_game, state, GAME_KIND_CHESS)


async def edit_chess_game_message(context, target: MessageTarget, game_id: str, state: ChessState, rated: bool, database: Database) -> None:
    if state.global_game:
        db_game = await database.get_game(game_id)
        if db_game is not None:
            await edit_global_game_messages(context.bot, database, db_game, state)
        return
    white = await database.get_user(state.white_user_id)
    black = await database.get_user(state.black_user_id)
    lang = i18n.db_user_lang(white)
    text = render_chess_message(
        state,
        display_name_from_db_user(white),
        display_name_from_db_user(black),
        rated,
        lang,
    )
    keyboard = render_chess_keyboard(game_id, state, lang)
    if target.inline_message_id:
        await context.bot.edit_message_text(inline_message_id=target.inline_message_id, text=text, reply_markup=keyboard)
    else:
        await context.bot.edit_message_text(chat_id=target.chat_id, message_id=target.message_id, text=text, reply_markup=keyboard)


async def edit_chess_confirmation_message(context, target: MessageTarget, game_id: str, state: ChessState, database: Database) -> None:
    white = await database.get_user(state.white_user_id)
    black = await database.get_user(state.black_user_id)
    lang = i18n.db_user_lang(black)
    text = render_chess_confirmation_message(
        state,
        display_name_from_db_user(white),
        display_name_from_db_user(black),
        lang,
    )
    keyboard = render_chess_confirmation_keyboard(game_id, lang)
    if target.inline_message_id:
        await context.bot.edit_message_text(inline_message_id=target.inline_message_id, text=text, reply_markup=keyboard)
    else:
        await context.bot.edit_message_text(chat_id=target.chat_id, message_id=target.message_id, text=text, reply_markup=keyboard)


def apply_chess_robot_turn(state: ChessState) -> list[tuple[int, int, str, dict]]:
    if state.robot_user_id is None or state.current_user_id() != state.robot_user_id:
        return []
    difficulty = parse_difficulty(state.robot_difficulty or RobotDifficulty.NORMAL.value) or RobotDifficulty.NORMAL
    applied: list[tuple[int, int, str, dict]] = []
    while state.status is not ChessStatus.FINISHED and state.current_user_id() == state.robot_user_id:
        board = state.board()
        move = choose_chess_robot_move(board, difficulty)
        if move is None:
            state.finish_if_game_over(board)
            break
        move_number = board.fullmove_number
        move_text = board.san(move)
        state.apply_move(move)
        applied.append((move_number, state.robot_user_id, move_text, state.to_json()))
    return applied
