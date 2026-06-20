from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, replace

from telegram import CallbackQuery, ReplyParameters, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import i18n
from .commands import (
    GAME_KIND_DRAUGHTS,
    create_draughts_game_message,
    create_robot_game_message,
    display_name_from_db_user,
    get_database,
    render_stats_text,
    status_text,
    telegram_user_id,
    upsert_user_from_telegram,
)
from .db import Database, FinishGame, GameOutcome, GameStateUpdate, NewGame, NewMove, UpsertChat, now_text
from .economy import (
    award_finished_game_currency,
    charge_pvp_entry_fee_once,
    configure_pvp_prize,
    pvp_players_without_entry_fee,
)
from .games.draughts import (
    Coord,
    DraughtsMove,
    DraughtsState,
    GameStatus,
    PieceColor,
    is_playable_square,
    parse_coord_id,
    parse_move_id,
)
from .games.robot import RobotDifficulty, choose_robot_move, parse_difficulty
from .global_matchmaking import edit_global_game_messages, finish_global_game, send_global_game_stats
from .i18n import Lang
from .render.text_board import (
    move_label,
    render_draughts_confirmation_keyboard,
    render_draughts_confirmation_message,
    render_draughts_keyboard,
    render_draughts_message,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageTarget:
    chat_id: int | None = None
    message_id: int | None = None
    inline_message_id: str | None = None


@dataclass(frozen=True)
class ParsedCallback:
    game_id: str
    action: str
    value: str | None = None
    selection: str | None = None

    @classmethod
    def parse(cls, data: str) -> "ParsedCallback | None":
        parts = data.split(":", 3)
        if len(parts) < 3 or parts[0] != "dg":
            return None
        game_id = parts[1]
        action = parts[2]
        value = parts[3] if len(parts) == 4 else None
        if action == "sq" and value:
            coord, _, selection = value.partition(":")
            try:
                parse_coord_id(coord)
                if selection and selection != "__":
                    parse_coord_id(selection)
            except ValueError:
                return None
            return cls(game_id, action, coord, selection or None)
        if game_id == "robot" and (difficulty := parse_difficulty(action)) is not None:
            return cls(game_id, "robot", difficulty.value)
        if action == "m" and value is not None:
            return cls(game_id, action, value) if value.isdigit() else None
        if action == "mv" and value:
            return cls(game_id, action, value)
        if action in {"resign", "stats", "pad", "join", "joinu", "ij", "accept", "again"}:
            return cls(game_id, action)
        return None


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    lang = i18n.user_lang(query.from_user)
    try:
        await dispatch_callback(query, context)
    except Exception:
        await query.answer(i18n.generic_error(lang), show_alert=False)
        raise


async def dispatch_callback(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = i18n.user_lang(query.from_user)
    if query.data is None:
        await query.answer(i18n.button_no_action(lang))
        return
    parsed = ParsedCallback.parse(query.data)
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
    if parsed.action == "ij":
        if target.inline_message_id is None:
            await query.answer(i18n.inline_only_button(lang))
            return
        await handle_inline_join_callback(context, database, query, target.inline_message_id, parsed.game_id)
    elif parsed.action in {"join", "joinu"}:
        if target.chat_id is None or target.message_id is None:
            await query.answer(i18n.post_new_invite_to_join(lang))
            return
        await handle_join_callback(context, database, query, target, parsed.game_id, parsed.action == "join")
    elif parsed.action == "accept":
        await handle_accept_callback(context, database, query, target, parsed.game_id)
    elif parsed.action == "robot" and parsed.value is not None:
        await handle_robot_start_callback(context, database, query, target, parsed.value)
    elif parsed.action in {"mv", "m"}:
        await handle_move_callback(context, database, query, target, parsed)
    elif parsed.action == "sq" and parsed.value is not None:
        await handle_square_callback(
            context,
            database,
            query,
            target,
            parsed.game_id,
            parse_coord_id(parsed.value),
            parse_coord_id(parsed.selection) if parsed.selection and parsed.selection != "__" else None,
        )
    elif parsed.action == "resign":
        await handle_resign_callback(context, database, query, target, parsed.game_id)
    elif parsed.action == "stats":
        await handle_stats_callback(context, database, query, target.chat_id, target.message_id, parsed.game_id)
    elif parsed.action == "again":
        await handle_again_callback(context, database, query, target, parsed.game_id)
    else:
        await query.answer()


async def handle_move_callback(context, database: Database, query: CallbackQuery, target: MessageTarget, parsed: ParsedCallback) -> None:
    lang = i18n.user_lang(query.from_user)
    db_game = await database.get_game(parsed.game_id)
    if db_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    if db_game.game_kind != GAME_KIND_DRAUGHTS:
        await query.answer(i18n.wrong_game_kind(lang))
        return
    state = DraughtsState.from_json(db_game.state)
    if state.global_game:
        lang = Lang.EN
    if state.status is GameStatus.CONFIRMING:
        await query.answer(i18n.game_not_started(lang))
        return
    if state.status is GameStatus.FINISHED:
        await query.answer(i18n.game_already_over(lang))
        return
    user_id = telegram_user_id(query.from_user)
    if state.current_user_id() != user_id:
        await query.answer(i18n.not_your_turn(lang))
        return
    legal_moves = state.legal_moves()
    if parsed.action == "mv" and parsed.value:
        move = parse_move_id(parsed.value)
    else:
        index = int(parsed.value or "0")
        if index >= len(legal_moves):
            await query.answer(i18n.move_unavailable(lang))
            return
        move = legal_moves[index]
    if move not in legal_moves:
        await query.answer(i18n.move_illegal(lang))
        return
    await query.answer()
    await play_move_and_update(context, database, query, target, db_game, state, move, user_id)


async def handle_square_callback(
    context,
    database: Database,
    query: CallbackQuery,
    target: MessageTarget,
    game_id: str,
    coord: Coord,
    callback_selected: Coord | None = None,
) -> None:
    lang = i18n.user_lang(query.from_user)
    db_game = await database.get_game(game_id)
    if db_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    if db_game.game_kind != GAME_KIND_DRAUGHTS:
        await query.answer(i18n.wrong_game_kind(lang))
        return
    state = DraughtsState.from_json(db_game.state)
    if state.global_game:
        lang = Lang.EN
    if state.status is GameStatus.CONFIRMING:
        await query.answer(i18n.game_not_started(lang))
        return
    if state.status is GameStatus.FINISHED:
        await query.answer(i18n.game_already_over(lang))
        return
    user_id = telegram_user_id(query.from_user)
    if state.current_user_id() != user_id:
        await query.answer(i18n.not_your_turn(lang))
        return
    if not is_playable_square(coord):
        await query.answer()
        return

    piece = state.board[coord.row][coord.col]
    if piece is not None:
        if piece.color is not state.turn:
            await query.answer(i18n.opponents_piece(lang))
            return
        if state.must_continue_from and state.must_continue_from != coord:
            await query.answer(i18n.must_continue_capture(lang))
            return
        if not can_select_piece(state, coord):
            await query.answer(i18n.capture_mandatory(lang) if state.has_forced_capture() else i18n.piece_no_legal_moves(lang))
            return
        state.selected = coord
        await query.answer()
        await edit_game_message(context, target, db_game.id, state, db_game.rated, database)
        return

    from_coord = state.must_continue_from or state.selected or callback_selected
    if from_coord:
        move = move_from_selected_to(state, from_coord, coord)
        if move:
            await query.answer()
            await play_move_and_update(context, database, query, target, db_game, state, move, user_id)
            return
    await query.answer()


async def handle_resign_callback(context, database: Database, query: CallbackQuery, target: MessageTarget, game_id: str) -> None:
    lang = i18n.user_lang(query.from_user)
    db_game = await database.get_game(game_id)
    if db_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    state = DraughtsState.from_json(db_game.state)
    if state.global_game:
        lang = Lang.EN
    if state.status is GameStatus.CONFIRMING:
        await query.answer(i18n.game_not_started(lang))
        return
    if state.status is GameStatus.FINISHED:
        await query.answer(i18n.game_already_over(lang))
        return
    user_id = telegram_user_id(query.from_user)
    resigning_color = state.user_color(user_id)
    if resigning_color is None:
        await query.answer(i18n.only_player_can_resign(lang))
        return
    state.status = GameStatus.FINISHED
    state.winner = PieceColor.WHITE if resigning_color is PieceColor.BLACK else PieceColor.BLACK
    state.result_reason = "resignation"
    state.selected = None
    state.must_continue_from = None
    await query.answer()
    await database.update_game_state(GameStateUpdate(db_game.id, target.message_id, status_text(state), state, None))
    await finish_rated_game(database, db_game, state)
    await edit_game_message(context, target, db_game.id, state, db_game.rated, database)


async def handle_stats_callback(
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
        state = DraughtsState.from_json(db_game.state)
        if state.global_game:
            await send_global_game_stats(context, database, query, GAME_KIND_DRAUGHTS, reply_to_message_id)
            return
    stats = await database.ensure_user_stats(chat_id, telegram_user_id(query.from_user), GAME_KIND_DRAUGHTS)
    wallet = await database.ensure_global_wallet(telegram_user_id(query.from_user))
    stats = replace(stats, kyzma_coin_balance=wallet.kyzma_coin_balance)
    reply_parameters = (
        ReplyParameters(message_id=reply_to_message_id)
        if reply_to_message_id is not None
        else None
    )
    await query.answer()
    await context.bot.send_message(
        chat_id=chat_id,
        text=render_stats_text(lang, stats, query.from_user),
        parse_mode=ParseMode.HTML,
        reply_parameters=reply_parameters,
    )


async def handle_join_callback(
    context,
    database: Database,
    query: CallbackQuery,
    target: MessageTarget,
    challenger_id_text: str,
    rated: bool,
) -> None:
    lang = i18n.user_lang(query.from_user)
    if query.from_user.is_bot:
        await query.answer(i18n.bots_cannot_join(lang))
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
            await create_draughts_confirmation_message(context, database, target, challenger_id, joiner_id)
        else:
            await create_draughts_game_message(
                context.bot,
                database,
                target.chat_id,
                target.message_id,
                challenger_id,
                joiner_id,
                False,
            )
    except sqlite3.IntegrityError:
        logger.info("join ignored: active game already exists on message", extra={"chat_id": target.chat_id, "message_id": target.message_id})
        await query.answer(i18n.invite_already_started(lang))
        return
    except InsufficientKyzmaCoins as exc:
        await query.answer(i18n.not_enough_kyzma_coins(lang, exc.cost), show_alert=True)
        return
    await query.answer()


class InsufficientKyzmaCoins(Exception):
    def __init__(self, cost: int, user_ids: tuple[int, ...]):
        super().__init__("not enough kyzma-coins")
        self.cost = cost
        self.user_ids = user_ids


async def create_draughts_confirmation_message(
    context,
    database: Database,
    target: MessageTarget,
    challenger_id: int,
    joiner_id: int,
):
    if target.chat_id is None or target.message_id is None:
        raise ValueError("rated confirmation requires a chat message target")
    state = DraughtsState.new(challenger_id, joiner_id)
    state.status = GameStatus.CONFIRMING
    await configure_pvp_prize(database, target.chat_id, challenger_id, joiner_id, GAME_KIND_DRAUGHTS, state)
    cost = state.kyzma_prize_base or 0
    insufficient_user_ids = await pvp_players_without_entry_fee(database, target.chat_id, challenger_id, joiner_id, GAME_KIND_DRAUGHTS, state)
    if insufficient_user_ids:
        raise InsufficientKyzmaCoins(cost, insufficient_user_ids)
    db_game = await database.create_game(NewGame(
        chat_id=target.chat_id,
        message_id=target.message_id,
        inline_message_id=None,
        game_kind=GAME_KIND_DRAUGHTS,
        status=status_text(state),
        rated=True,
        state=state,
        current_turn_user_id=None,
        black_user_id=challenger_id,
        white_user_id=joiner_id,
    ))
    await edit_confirmation_message(context, target, db_game.id, state, database)
    return db_game


async def handle_accept_callback(context, database: Database, query: CallbackQuery, target: MessageTarget, game_id: str) -> None:
    lang = i18n.user_lang(query.from_user)
    db_game = await database.get_game(game_id)
    if db_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    if db_game.game_kind != GAME_KIND_DRAUGHTS:
        await query.answer(i18n.wrong_game_kind(lang))
        return
    state = DraughtsState.from_json(db_game.state)
    if state.status is not GameStatus.CONFIRMING:
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
        GAME_KIND_DRAUGHTS,
        state,
    )
    if insufficient_user_ids:
        state.accepted_user_ids = [
            accepted_user_id
            for accepted_user_id in state.accepted_user_ids
            if accepted_user_id not in set(insufficient_user_ids)
        ]
        await database.update_game_state(GameStateUpdate(
            game_id=db_game.id,
            message_id=target.message_id,
            status=status_text(state),
            state=state,
            current_turn_user_id=None,
        ))
        await edit_confirmation_message(context, target, db_game.id, state, database)
        await query.answer(i18n.not_enough_kyzma_coins(lang, cost), show_alert=True)
        return

    accepted = set(state.accepted_user_ids)
    was_already_accepted = user_id in accepted
    accepted.add(user_id)
    state.accepted_user_ids = sorted(accepted)

    if {state.black_user_id, state.white_user_id}.issubset(accepted):
        charge_result = await charge_pvp_entry_fee_once(database, db_game, state, GAME_KIND_DRAUGHTS)
        if not charge_result.success:
            state.accepted_user_ids = [
                accepted_user_id
                for accepted_user_id in state.accepted_user_ids
                if accepted_user_id not in set(charge_result.insufficient_user_ids)
            ]
            await database.update_game_state(GameStateUpdate(
                game_id=db_game.id,
                message_id=target.message_id,
                status=status_text(state),
                state=state,
                current_turn_user_id=None,
            ))
            await edit_confirmation_message(context, target, db_game.id, state, database)
            await query.answer(i18n.not_enough_kyzma_coins(lang, cost), show_alert=True)
            return
        state.status = GameStatus.IN_PROGRESS
        state.accepted_user_ids = []
        await database.update_game_state(GameStateUpdate(
            game_id=db_game.id,
            message_id=target.message_id,
            status=status_text(state),
            state=state,
            current_turn_user_id=state.current_user_id(),
        ))
        await edit_game_message(context, target, db_game.id, state, db_game.rated, database)
        await query.answer(i18n.game_started(lang))
        return

    await database.update_game_state(GameStateUpdate(
        game_id=db_game.id,
        message_id=target.message_id,
        status=status_text(state),
        state=state,
        current_turn_user_id=None,
    ))
    await edit_confirmation_message(context, target, db_game.id, state, database)
    await query.answer(i18n.game_accept_waiting(lang) if was_already_accepted else i18n.game_accept_recorded(lang))


async def handle_robot_start_callback(
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
        await create_robot_game_message(
            context.bot,
            database,
            target.chat_id,
            target.message_id,
            query.from_user,
            difficulty,
        )
    except sqlite3.IntegrityError:
        logger.info("robot game start ignored: active game already exists on message", extra={"chat_id": target.chat_id, "message_id": target.message_id})


async def handle_inline_join_callback(context, database: Database, query: CallbackQuery, inline_message_id: str, challenger_id_text: str) -> None:
    lang = i18n.user_lang(query.from_user)
    if query.from_user.is_bot:
        await query.answer(i18n.bots_cannot_join(lang))
        return
    try:
        challenger_id = int(challenger_id_text)
    except ValueError:
        await query.answer(i18n.invite_invalid_post(lang))
        return
    joiner_id = telegram_user_id(query.from_user)
    if joiner_id == challenger_id:
        await query.answer(i18n.cannot_join_own_invite(lang))
        return
    if await database.get_active_game_by_inline_message(inline_message_id):
        logger.info("inline join rejected: active game already exists", extra={"inline_message_id": inline_message_id})
        await query.answer(i18n.invite_already_started(lang))
        return
    invite_claim = await claim_inline_invite(database, inline_message_id, challenger_id)
    if invite_claim == "mismatch":
        logger.info(
            "inline join rejected: stored invite challenger mismatch",
            extra={"inline_message_id": inline_message_id, "challenger_id": challenger_id},
        )
        await query.answer(i18n.invite_no_longer_valid(lang))
        return
    await database.upsert_user(upsert_user_from_telegram(query.from_user))
    await ensure_inline_chat(database)
    state = DraughtsState.new(challenger_id, joiner_id)
    black = await ensure_inline_challenger_user(database, challenger_id)
    white = await database.get_user(joiner_id)
    try:
        db_game = await database.create_game(NewGame(
            chat_id=0,
            message_id=None,
            inline_message_id=inline_message_id,
            game_kind=GAME_KIND_DRAUGHTS,
            status=status_text(state),
            rated=False,
            state=state,
            current_turn_user_id=state.current_user_id(),
            black_user_id=challenger_id,
            white_user_id=joiner_id,
        ))
    except sqlite3.IntegrityError:
        logger.info("inline join rejected: game insert hit uniqueness/integrity constraint", extra={"inline_message_id": inline_message_id})
        await query.answer(i18n.invite_already_started(lang))
        return
    board_lang = i18n.db_user_lang(black)
    await context.bot.edit_message_text(
        inline_message_id=inline_message_id,
        text=render_draughts_message(state, display_name_from_db_user(black), display_name_from_db_user(white), False, board_lang),
        reply_markup=render_draughts_keyboard(db_game.id, state, board_lang),
    )
    await query.answer()


async def ensure_inline_chat(database: Database) -> None:
    await database.upsert_chat(UpsertChat(telegram_chat_id=0, title="Inline message", kind="inline"))


async def claim_inline_invite(database: Database, inline_message_id: str, challenger_id: int) -> str:
    invite = await database.get_and_delete_inline_invite(inline_message_id)
    if invite is not None:
        return "valid" if invite.challenger_id == challenger_id else "mismatch"

    # Telegram only sends chosen_inline_result when inline feedback is enabled.
    # The callback payload already contains the challenger id, and Telegram's
    # inline_message_id plus the unique active-game index protect the message
    # from being claimed twice.
    return "valid"


async def ensure_inline_challenger_user(database: Database, challenger_id: int):
    try:
        return await database.get_user(challenger_id)
    except LookupError:
        await database.upsert_user(upsert_user_from_telegram_placeholder(challenger_id))
        return await database.get_user(challenger_id)


def upsert_user_from_telegram_placeholder(user_id: int):
    from .db import UpsertUser

    return UpsertUser(
        telegram_user_id=user_id,
        username=None,
        first_name=f"user {user_id}",
        last_name=None,
        language_code=None,
    )


async def handle_again_callback(context, database: Database, query: CallbackQuery, target: MessageTarget, game_id: str) -> None:
    lang = i18n.user_lang(query.from_user)
    old_game = await database.get_game(game_id)
    if old_game is None:
        await query.answer(i18n.game_not_found(lang))
        return
    if old_game.game_kind != GAME_KIND_DRAUGHTS:
        await query.answer(i18n.wrong_game_kind(lang))
        return
    old_state = DraughtsState.from_json(old_game.state)
    if old_state.global_game:
        await query.answer("Use /play_random to find another global opponent.")
        return
    if old_state.robot_user_id is not None:
        await handle_robot_again_callback(context, database, query, target, old_state)
        return
    if old_state.status is not GameStatus.FINISHED:
        await query.answer(i18n.finish_before_rematch(lang))
        return
    user_id = telegram_user_id(query.from_user)
    if user_id not in {old_game.black_user_id, old_game.white_user_id}:
        await query.answer(i18n.only_players_can_rematch(lang))
        return
    if old_state.rematch_requested_by is None:
        old_state.rematch_requested_by = user_id
        await database.update_game_state(GameStateUpdate(old_game.id, None, status_text(old_state), old_state, None))
        await edit_game_message(context, target, old_game.id, old_state, old_game.rated, database)
        await query.answer(i18n.rematch_offer_sent(lang))
        return
    if old_state.rematch_requested_by == user_id:
        await query.answer(i18n.rematch_waiting_for_opponent(lang))
        return

    state = DraughtsState.new(old_game.white_user_id, old_game.black_user_id)
    if old_game.rated and old_game.chat_id != 0:
        await configure_pvp_prize(database, old_game.chat_id, state.black_user_id, state.white_user_id, GAME_KIND_DRAUGHTS, state)
    new_game = await database.create_game(NewGame(
        chat_id=old_game.chat_id,
        message_id=target.message_id,
        inline_message_id=target.inline_message_id,
        game_kind=GAME_KIND_DRAUGHTS,
        status=status_text(state),
        rated=old_game.rated,
        state=state,
        current_turn_user_id=state.current_user_id(),
        black_user_id=old_game.white_user_id,
        white_user_id=old_game.black_user_id,
    ))
    await edit_game_message(context, target, new_game.id, state, old_game.rated, database)
    await query.answer()


async def handle_robot_again_callback(
    context,
    database: Database,
    query: CallbackQuery,
    target: MessageTarget,
    old_state: DraughtsState,
) -> None:
    lang = i18n.user_lang(query.from_user)
    if old_state.status is not GameStatus.FINISHED:
        await query.answer(i18n.finish_before_rematch(lang))
        return
    user_id = telegram_user_id(query.from_user)
    if old_state.user_color(user_id) is None or user_id == old_state.robot_user_id:
        await query.answer(i18n.only_players_can_rematch(lang))
        return
    if target.chat_id is None or target.message_id is None:
        await query.answer(i18n.button_no_context(lang))
        return
    difficulty = parse_difficulty(old_state.robot_difficulty or RobotDifficulty.NORMAL.value) or RobotDifficulty.NORMAL
    await query.answer()
    await create_robot_game_message(
        context.bot,
        database,
        target.chat_id,
        target.message_id,
        query.from_user,
        difficulty,
    )


async def play_move_and_update(
    context,
    database: Database,
    query: CallbackQuery,
    target: MessageTarget,
    db_game,
    state: DraughtsState,
    move: DraughtsMove,
    user_id: int,
) -> None:
    move_number = state.move_number
    result = state.apply_move(move)
    if state.global_game and result.turn_ended and state.status is GameStatus.IN_PROGRESS:
        state.turn_started_at = now_text()
    await database.insert_move(NewMove(
        game_id=db_game.id,
        move_number=move_number,
        user_id=user_id,
        move_text=move_label(move, bool(result.captured)),
        state_after=state,
    ))
    robot_moves = apply_robot_turn(state)
    for robot_move, robot_move_number, robot_captured, robot_state_after in robot_moves:
        await database.insert_move(NewMove(
            game_id=db_game.id,
            move_number=robot_move_number,
            user_id=state.robot_user_id,
            move_text=move_label(robot_move, robot_captured),
            state_after=robot_state_after,
        ))
    await database.update_game_state(GameStateUpdate(
        game_id=db_game.id,
        message_id=target.message_id,
        status=status_text(state),
        state=state,
        current_turn_user_id=None if state.status is GameStatus.FINISHED else state.current_user_id(),
    ))
    if state.status is GameStatus.FINISHED:
        await finish_rated_game(database, db_game, state)
    await edit_game_message(context, target, db_game.id, state, db_game.rated, database)


async def finish_rated_game(database: Database, db_game, state: DraughtsState) -> None:
    if not await database.finish_game(FinishGame(db_game.id, state.winner_user_id(), state.result_reason)):
        return
    if state.global_game:
        await finish_global_game(database, db_game, state)
        return
    if db_game.rated:
        await database.update_stats_after_game(GameOutcome(
            chat_id=db_game.chat_id,
            game_kind=GAME_KIND_DRAUGHTS,
            black_user_id=db_game.black_user_id,
            white_user_id=db_game.white_user_id,
            winner_user_id=state.winner_user_id(),
        ))
    await award_finished_game_currency(database, db_game, state, GAME_KIND_DRAUGHTS)


async def edit_game_message(context, target: MessageTarget, game_id: str, state: DraughtsState, rated: bool, database: Database) -> None:
    if state.global_game:
        db_game = await database.get_game(game_id)
        if db_game is not None:
            await edit_global_game_messages(context.bot, database, db_game, state)
        return
    black = await database.get_user(state.black_user_id)
    white = await database.get_user(state.white_user_id)
    lang_source = white if state.robot_user_id == state.black_user_id else black
    lang = i18n.db_user_lang(lang_source)
    text = render_draughts_message(state, display_name_from_db_user(black), display_name_from_db_user(white), rated, lang)
    keyboard = render_draughts_keyboard(game_id, state, lang)
    if target.inline_message_id:
        await context.bot.edit_message_text(inline_message_id=target.inline_message_id, text=text, reply_markup=keyboard)
    else:
        await context.bot.edit_message_text(chat_id=target.chat_id, message_id=target.message_id, text=text, reply_markup=keyboard)


async def edit_confirmation_message(context, target: MessageTarget, game_id: str, state: DraughtsState, database: Database) -> None:
    black = await database.get_user(state.black_user_id)
    white = await database.get_user(state.white_user_id)
    lang = i18n.db_user_lang(black)
    text = render_draughts_confirmation_message(
        state,
        display_name_from_db_user(black),
        display_name_from_db_user(white),
        lang,
    )
    keyboard = render_draughts_confirmation_keyboard(game_id, lang)
    if target.inline_message_id:
        await context.bot.edit_message_text(inline_message_id=target.inline_message_id, text=text, reply_markup=keyboard)
    else:
        await context.bot.edit_message_text(chat_id=target.chat_id, message_id=target.message_id, text=text, reply_markup=keyboard)


def can_select_piece(state: DraughtsState, coord: Coord) -> bool:
    return state.is_current_players_piece(coord) and bool(state.legal_moves_for_piece(coord))


def move_from_selected_to(state: DraughtsState, from_: Coord, destination: Coord) -> DraughtsMove | None:
    for move in state.legal_moves_for_piece(from_):
        if move.sequence and move.sequence[0] == destination:
            return move
    return None


def apply_robot_turn(state: DraughtsState) -> list[tuple[DraughtsMove, int, bool, dict]]:
    if state.robot_user_id is None or state.current_user_id() != state.robot_user_id:
        return []
    difficulty = parse_difficulty(state.robot_difficulty or RobotDifficulty.NORMAL.value) or RobotDifficulty.NORMAL
    applied: list[tuple[DraughtsMove, int, bool, dict]] = []
    while state.status is not GameStatus.FINISHED and state.current_user_id() == state.robot_user_id:
        move = choose_robot_move(state, difficulty)
        if move is None:
            break
        move_number = state.move_number
        result = state.apply_move(move)
        applied.append((move, move_number, bool(result.captured), state.to_json()))
    return applied
