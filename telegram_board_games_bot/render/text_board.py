from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .. import i18n
from ..games.draughts import (
    BOARD_SIZE,
    Coord,
    DraughtsMove,
    DraughtsState,
    GameStatus,
    Piece,
    PieceColor,
    PieceKind,
    coord_to_id,
    is_playable_square,
)
from ..i18n import Lang

CALLBACK_LIMIT = 64
TILE_PADDING = "\u2800"
TILE_EMPTY = "\u2800"
TILE_PLAYABLE_EMPTY = "·"
TILE_BLACK_MAN = "⚫"
TILE_WHITE_MAN = "⚪"
TILE_BLACK_KING = "⬛"
TILE_WHITE_KING = "⬜"
TILE_CAPTURE_TARGET = "❌"


def render_draughts_message(
    state: DraughtsState,
    black_name: str,
    white_name: str,
    rated: bool,
    lang: Lang,
) -> str:
    if state.status is GameStatus.CONFIRMING:
        return render_draughts_confirmation_message(state, black_name, white_name, lang).rstrip() + "\n"

    lines: list[str] = []
    if state.status is GameStatus.IN_PROGRESS:
        lines.append(i18n.rated_header(lang, rated))
        lines.append("")
        lines.append(roster_line(lang, black_name, PieceColor.BLACK))
        lines.append(roster_line(lang, white_name, PieceColor.WHITE))
        if state.kyzma_prize_base and state.kyzma_prize_multiplier and state.kyzma_prize:
            lines.append(i18n.kyzma_prize_line(lang, state.kyzma_prize_base, state.kyzma_prize_multiplier, state.kyzma_prize))
        lines.append(i18n.move_line(lang, state.move_number))
        lines.append(i18n.turn_line(lang, name_for_turn(state.turn, black_name, white_name), color_symbol(state.turn)))
    else:
        lines.append(i18n.game_over_header(lang))
        if state.winner is PieceColor.BLACK:
            lines.append(i18n.winner_line(lang, black_name, color_symbol(PieceColor.BLACK)))
        elif state.winner is PieceColor.WHITE:
            lines.append(i18n.winner_line(lang, white_name, color_symbol(PieceColor.WHITE)))
        else:
            lines.append(i18n.winner_draw_line(lang))
        if state.result_reason:
            lines.append(i18n.reason_line(lang, human_reason(lang, state, state.result_reason)))
        lines.append(i18n.move_line(lang, state.move_number))
        lines.append("")
        lines.append(roster_line(lang, black_name, PieceColor.BLACK))
        lines.append(roster_line(lang, white_name, PieceColor.WHITE))
        if state.kyzma_prize_base and state.kyzma_prize_multiplier and state.kyzma_prize:
            lines.append(i18n.kyzma_prize_line(lang, state.kyzma_prize_base, state.kyzma_prize_multiplier, state.kyzma_prize))
        if state.rematch_requested_by is not None:
            requester_name = black_name if state.rematch_requested_by == state.black_user_id else white_name
            lines.append(i18n.rematch_offer_line(lang, requester_name))
    return "\n".join(lines).rstrip() + "\n"


def roster_line(lang: Lang, name: str, color: PieceColor) -> str:
    return f"{name} — {color_symbol(color)} {i18n.color_label(lang, color)}"


def render_draughts_invite_message(challenger_name: str, lang: Lang, challenger_value: int | None = None) -> str:
    lines = [
        i18n.draughts_invite_header(lang),
        "",
        f"{challenger_name} — {color_symbol(PieceColor.BLACK)} {i18n.color_label(lang, PieceColor.BLACK)}",
    ]
    if challenger_value is not None:
        lines.append(i18n.player_value_line(lang, challenger_value))
    lines.append(i18n.waiting_for_opponent(lang))
    return "\n".join(lines)


def render_draughts_invite_keyboard(challenger_user_id: int, lang: Lang) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(i18n.join_rated_button(lang), callback_data=f"dg:{challenger_user_id}:join")],
        [InlineKeyboardButton(i18n.join_unrated_button(lang), callback_data=f"dg:{challenger_user_id}:joinu")],
    ])


def render_draughts_inline_invite_keyboard(challenger_user_id: int, lang: Lang) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(i18n.join_as_white_button(lang), callback_data=f"dg:{challenger_user_id}:ij")
    ]])


def render_robot_difficulty_keyboard(lang: Lang) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(i18n.robot_easy_button(lang), callback_data="dg:robot:easy"),
        InlineKeyboardButton(i18n.robot_normal_button(lang), callback_data="dg:robot:normal"),
        InlineKeyboardButton(i18n.robot_hard_button(lang), callback_data="dg:robot:hard"),
    ]])


def render_draughts_confirmation_message(
    state: DraughtsState,
    black_name: str,
    white_name: str,
    lang: Lang,
) -> str:
    lines = [
        i18n.confirm_game_header(lang),
        "",
        roster_line(lang, black_name, PieceColor.BLACK),
        roster_line(lang, white_name, PieceColor.WHITE),
    ]
    if state.kyzma_prize_base is not None:
        lines.append(i18n.kyzma_game_cost_line(lang, state.kyzma_prize_base))
        lines.append(i18n.kyzma_entry_fee_notice(lang))
    if state.kyzma_prize_base and state.kyzma_prize_multiplier and state.kyzma_prize:
        lines.append(i18n.kyzma_prize_line(lang, state.kyzma_prize_base, state.kyzma_prize_multiplier, state.kyzma_prize))
    lines.extend([
        "",
        i18n.both_players_must_accept(lang),
        i18n.accepted_count_line(lang, len(set(state.accepted_user_ids)), 2),
    ])
    return "\n".join(lines)


def render_draughts_confirmation_keyboard(game_id: str, lang: Lang) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(i18n.accept_game_button(lang), callback_data=compact_callback_data(game_id, "accept"))
    ]])


def render_draughts_keyboard(game_id: str, state: DraughtsState, lang: Lang) -> InlineKeyboardMarkup:
    if state.status is GameStatus.CONFIRMING:
        return render_draughts_confirmation_keyboard(game_id, lang)
    if state.status is GameStatus.FINISHED:
        if state.global_game:
            return InlineKeyboardMarkup([[
                InlineKeyboardButton(i18n.stats_button(lang), callback_data=compact_callback_data(game_id, "stats")),
            ]])
        again_label = i18n.accept_rematch_button(lang) if state.rematch_requested_by is not None else i18n.play_again_button(lang)
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(again_label, callback_data=compact_callback_data(game_id, "again")),
            InlineKeyboardButton(i18n.stats_button(lang), callback_data=compact_callback_data(game_id, "stats")),
        ]])

    rows: list[list[InlineKeyboardButton]] = []
    for row in range(BOARD_SIZE):
        keyboard_row = []
        for col in range(BOARD_SIZE):
            coord = Coord(row, col)
            keyboard_row.append(InlineKeyboardButton(
                tile_button_text(state, coord),
                callback_data=square_callback_data(game_id, coord, state),
            ))
        rows.append(keyboard_row)
    rows.append([
        InlineKeyboardButton(i18n.resign_button(lang), callback_data=compact_callback_data(game_id, "resign")),
        InlineKeyboardButton(i18n.stats_button(lang), callback_data=compact_callback_data(game_id, "stats")),
    ])
    return InlineKeyboardMarkup(rows)


def tile_button_text(state: DraughtsState, coord: Coord) -> str:
    if is_captured_this_turn_square(state, coord):
        return padded_tile(TILE_CAPTURE_TARGET)
    return padded_tile(square_symbol(state, coord))


def padded_tile(symbol: str) -> str:
    return f"{TILE_PADDING}{symbol}{TILE_PADDING}"


def is_captured_this_turn_square(state: DraughtsState, coord: Coord) -> bool:
    return (
        state.must_continue_from is not None
        and coord in state.captured_this_turn
        and state.board[coord.row][coord.col] is None
    )


def square_symbol(state: DraughtsState, coord: Coord) -> str:
    if not is_playable_square(coord):
        return TILE_EMPTY
    piece = state.board[coord.row][coord.col]
    match piece:
        case Piece(color=PieceColor.BLACK, kind=PieceKind.MAN):
            return TILE_BLACK_MAN
        case Piece(color=PieceColor.BLACK, kind=PieceKind.KING):
            return TILE_BLACK_KING
        case Piece(color=PieceColor.WHITE, kind=PieceKind.MAN):
            return TILE_WHITE_MAN
        case Piece(color=PieceColor.WHITE, kind=PieceKind.KING):
            return TILE_WHITE_KING
        case _:
            return TILE_PLAYABLE_EMPTY


def square_callback_data(game_id: str, coord: Coord, state: DraughtsState) -> str:
    return compact_callback_data(game_id, f"sq:{coord_to_id(coord)}:{selection_token(state)}")


def selection_token(state: DraughtsState) -> str:
    selected = state.must_continue_from or state.selected
    return coord_to_id(selected) if selected else "__"


def compact_callback_data(game_id: str, action: str) -> str:
    callback_data = f"dg:{game_id}:{action}"
    if len(callback_data) <= CALLBACK_LIMIT:
        return callback_data
    max_game_id_len = CALLBACK_LIMIT - len(f"dg::{action}")
    return f"dg:{truncate_to_byte_len(game_id, max_game_id_len)}:{action}"


def truncate_to_byte_len(value: str, max_len: int) -> str:
    encoded = value.encode()
    if len(encoded) <= max_len:
        return value
    return encoded[:max_len].decode(errors="ignore")


def move_label(move: DraughtsMove, is_capture: bool) -> str:
    separator = "x" if is_capture else "-"
    return separator.join(coord_label(coord) for coord in [move.from_, *move.sequence])


def coord_label(coord: Coord) -> str:
    file = chr(ord("A") + coord.col)
    rank = 8 - coord.row
    return f"{file}{rank}"


def color_symbol(color: PieceColor) -> str:
    return "⚫" if color is PieceColor.BLACK else "⚪"


def name_for_turn(color: PieceColor, black_name: str, white_name: str) -> str:
    return black_name if color is PieceColor.BLACK else white_name


def human_reason(lang: Lang, state: DraughtsState, reason: str) -> str:
    if reason == "opponent has no legal moves":
        return i18n.reason_no_legal_moves(lang, losing_color_name(lang, state))
    if reason == "opponent has no pieces":
        return i18n.reason_no_pieces(lang, losing_color_name(lang, state))
    if reason == "resignation":
        return i18n.reason_resignation(lang)
    return reason[:1].upper() + reason[1:]


def losing_color_name(lang: Lang, state: DraughtsState) -> str:
    if state.winner is PieceColor.BLACK:
        return i18n.color_label(lang, PieceColor.WHITE)
    if state.winner is PieceColor.WHITE:
        return i18n.color_label(lang, PieceColor.BLACK)
    return i18n.player_word(lang)
