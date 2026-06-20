from __future__ import annotations

import chess
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .. import i18n
from ..games.chess_game import ChessState, ChessStatus
from ..games.draughts import PieceColor
from ..i18n import Lang
from .text_board import CALLBACK_LIMIT, truncate_to_byte_len

TILE_EMPTY = "\u3000"
WHITE_MARK = "▫"
BLACK_MARK = "▪"

PIECE_EMOJIS = {
    chess.WHITE: {
        chess.PAWN: "⚪",
        chess.ROOK: "🏰",
        chess.KNIGHT: "🎠",
        chess.BISHOP: "🐘",
        chess.QUEEN: "👸🏻",
        chess.KING: "🤴🏻",
    },
    chess.BLACK: {
        chess.PAWN: "⚫",
        chess.ROOK: "🏯",
        chess.KNIGHT: "🐴",
        chess.BISHOP: "🦣",
        chess.QUEEN: "👸🏿",
        chess.KING: "🤴🏿",
    },
}

PROMOTIONS = (
    (chess.QUEEN, "q", i18n.queen_button),
    (chess.ROOK, "r", i18n.rook_button),
    (chess.BISHOP, "b", i18n.bishop_button),
    (chess.KNIGHT, "n", i18n.knight_button),
)


def render_chess_message(
    state: ChessState,
    white_name: str,
    black_name: str,
    rated: bool,
    lang: Lang,
) -> str:
    if state.status is ChessStatus.CONFIRMING:
        return render_chess_confirmation_message(state, white_name, black_name, lang).rstrip() + "\n"

    board = state.board()
    lines: list[str] = []
    if state.status is ChessStatus.IN_PROGRESS:
        lines.append(i18n.chess_header(lang, rated))
        lines.append("")
        lines.append(chess_roster_line(lang, white_name, chess.WHITE))
        lines.append(chess_roster_line(lang, black_name, chess.BLACK))
        if state.kyzma_prize_base and state.kyzma_prize_multiplier and state.kyzma_prize:
            lines.append(i18n.kyzma_prize_line(lang, state.kyzma_prize_base, state.kyzma_prize_multiplier, state.kyzma_prize))
        lines.append(i18n.move_line(lang, board.fullmove_number))
        lines.append(i18n.turn_line(lang, name_for_turn(board.turn, white_name, black_name), chess_color_symbol(board.turn)))
        if board.is_check():
            lines.append(i18n.check_line(lang))
    else:
        lines.append(i18n.game_over_header(lang))
        if state.winner_user_id() == state.white_user_id:
            lines.append(i18n.winner_line(lang, white_name, chess_color_symbol(chess.WHITE)))
        elif state.winner_user_id() == state.black_user_id:
            lines.append(i18n.winner_line(lang, black_name, chess_color_symbol(chess.BLACK)))
        else:
            lines.append(i18n.winner_draw_line(lang))
        if state.result_reason:
            lines.append(i18n.reason_line(lang, human_reason(state.result_reason)))
        lines.append(i18n.move_line(lang, board.fullmove_number))
        lines.append("")
        lines.append(chess_roster_line(lang, white_name, chess.WHITE))
        lines.append(chess_roster_line(lang, black_name, chess.BLACK))
        if state.kyzma_prize_base and state.kyzma_prize_multiplier and state.kyzma_prize:
            lines.append(i18n.kyzma_prize_line(lang, state.kyzma_prize_base, state.kyzma_prize_multiplier, state.kyzma_prize))
    return "\n".join(lines).rstrip() + "\n"


def render_chess_invite_message(challenger_name: str, lang: Lang, challenger_value: int | None = None) -> str:
    lines = [
        i18n.chess_invite_header(lang),
        "",
        f"{challenger_name} — {chess_color_symbol(chess.BLACK)} {chess_color_label(lang, chess.BLACK)}",
    ]
    if challenger_value is not None:
        lines.append(i18n.player_value_line(lang, challenger_value))
    lines.append(i18n.waiting_for_opponent(lang))
    return "\n".join(lines)


def render_chess_invite_keyboard(challenger_user_id: int, lang: Lang) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(i18n.join_rated_button(lang), callback_data=f"ch:{challenger_user_id}:join")],
        [InlineKeyboardButton(i18n.join_unrated_button(lang), callback_data=f"ch:{challenger_user_id}:joinu")],
    ])


def render_chess_robot_difficulty_keyboard(lang: Lang) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(i18n.robot_easy_button(lang), callback_data="ch:robot:easy"),
        InlineKeyboardButton(i18n.robot_normal_button(lang), callback_data="ch:robot:normal"),
        InlineKeyboardButton(i18n.robot_hard_button(lang), callback_data="ch:robot:hard"),
    ]])


def render_chess_confirmation_message(
    state: ChessState,
    white_name: str,
    black_name: str,
    lang: Lang,
) -> str:
    lines = [
        i18n.confirm_chess_game_header(lang),
        "",
        chess_roster_line(lang, white_name, chess.WHITE),
        chess_roster_line(lang, black_name, chess.BLACK),
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


def render_chess_confirmation_keyboard(game_id: str, lang: Lang) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(i18n.accept_game_button(lang), callback_data=compact_callback_data(game_id, "accept"))
    ]])


def render_chess_keyboard(game_id: str, state: ChessState, lang: Lang) -> InlineKeyboardMarkup:
    if state.status is ChessStatus.CONFIRMING:
        return render_chess_confirmation_keyboard(game_id, lang)
    if state.status is ChessStatus.FINISHED:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(i18n.stats_button(lang), callback_data=compact_callback_data(game_id, "stats")),
        ]])
    if state.promotion_from and state.promotion_to:
        rows = [[InlineKeyboardButton(i18n.promote_to(lang), callback_data=compact_callback_data(game_id, "pad"))]]
        rows.extend([
            [
                InlineKeyboardButton(f"{piece_label(piece_type)} {label_func(lang)}", callback_data=compact_callback_data(game_id, f"promo:{token}"))
                for piece_type, token, label_func in PROMOTIONS
            ]
        ])
        rows.append([
            InlineKeyboardButton(i18n.resign_button(lang), callback_data=compact_callback_data(game_id, "resign")),
            InlineKeyboardButton(i18n.stats_button(lang), callback_data=compact_callback_data(game_id, "stats")),
        ])
        return InlineKeyboardMarkup(rows)

    board = state.board()
    rows: list[list[InlineKeyboardButton]] = []
    for rank in range(7, -1, -1):
        keyboard_row = []
        for file in range(8):
            square = chess.square(file, rank)
            keyboard_row.append(InlineKeyboardButton(
                square_button_text(board, square),
                callback_data=square_callback_data(game_id, square, state),
            ))
        rows.append(keyboard_row)
    rows.append([
        InlineKeyboardButton(i18n.resign_button(lang), callback_data=compact_callback_data(game_id, "resign")),
        InlineKeyboardButton(i18n.stats_button(lang), callback_data=compact_callback_data(game_id, "stats")),
    ])
    return InlineKeyboardMarkup(rows)


def square_button_text(board: chess.Board, square: chess.Square) -> str:
    piece = board.piece_at(square)
    return TILE_EMPTY if piece is None else piece_label(piece)


def piece_label(piece: chess.Piece | int) -> str:
    if isinstance(piece, int):
        return PIECE_EMOJIS[chess.WHITE][piece]
    return PIECE_EMOJIS[piece.color][piece.piece_type]


def square_callback_data(game_id: str, square: chess.Square, state: ChessState) -> str:
    selected = state.promotion_from or state.selected_square or "__"
    return compact_callback_data(game_id, f"sq:{chess.square_name(square)}:{selected}")


def compact_callback_data(game_id: str, action: str) -> str:
    callback_data = f"ch:{game_id}:{action}"
    if len(callback_data) <= CALLBACK_LIMIT:
        return callback_data
    max_game_id_len = CALLBACK_LIMIT - len(f"ch::{action}")
    return f"ch:{truncate_to_byte_len(game_id, max_game_id_len)}:{action}"


def chess_roster_line(lang: Lang, name: str, color: bool) -> str:
    return f"{name} — {chess_color_symbol(color)} {chess_color_label(lang, color)}"


def chess_color_symbol(color: bool) -> str:
    return WHITE_MARK if color == chess.WHITE else BLACK_MARK


def chess_color_label(lang: Lang, color: bool) -> str:
    return i18n.color_label(lang, PieceColor.WHITE if color == chess.WHITE else PieceColor.BLACK)


def name_for_turn(color: bool, white_name: str, black_name: str) -> str:
    return white_name if color == chess.WHITE else black_name


def human_reason(reason: str) -> str:
    return reason[:1].upper() + reason[1:]
