import chess

from telegram_board_games_bot.chess_callbacks import ParsedChessCallback
from telegram_board_games_bot.economy import (
    CHESS_PRIZE_MULTIPLIER_FACTOR,
    CHESS_PVP_COST_MULTIPLIER,
    multiplied_cost,
    set_kyzma_prize,
)
from telegram_board_games_bot.games.chess_game import ChessState, ChessStatus
from telegram_board_games_bot.games.chess_robot import choose_chess_robot_move
from telegram_board_games_bot.games.robot import RobotDifficulty
from telegram_board_games_bot.i18n import Lang
from telegram_board_games_bot.render.chess_board import (
    render_chess_invite_keyboard,
    render_chess_invite_message,
    render_chess_keyboard,
    render_chess_message,
)


class FixedRng:
    def choices(self, values, weights, k):
        return [3]


def test_chess_state_applies_legal_move_and_round_trips() -> None:
    state = ChessState.new(white_user_id=10, black_user_id=20)
    move = state.legal_move("e2", "e4")

    assert state.current_user_id() == 10
    assert move == chess.Move.from_uci("e2e4")

    state.apply_move(move)
    restored = ChessState.from_json(state.to_json())

    assert restored.current_user_id() == 20
    assert restored.board().piece_at(chess.E4) == chess.Piece(chess.PAWN, chess.WHITE)
    assert restored.status is ChessStatus.IN_PROGRESS


def test_chess_renderer_uses_readable_piece_markers_and_callbacks() -> None:
    state = ChessState.new(10, 20)
    state.kyzma_prize_base = 15
    state.kyzma_prize_multiplier = 6
    state.kyzma_prize = 90

    message = render_chess_message(state, "@white", "@black", True, Lang.EN)
    keyboard = render_chess_keyboard("game", state, Lang.EN)

    assert "Chess · Rated" in message
    assert "@white — ▫ White" in message
    assert "@black — ▪ Black" in message
    assert "Prize: 15 kyzma-coins ×6 = 90" in message
    assert len(keyboard.inline_keyboard) == 9
    assert keyboard.inline_keyboard[0][0].text == "🏯"
    assert keyboard.inline_keyboard[0][1].text == "🐴"
    assert keyboard.inline_keyboard[1][0].text == "⚫"
    assert keyboard.inline_keyboard[6][4].callback_data == "ch:game:sq:e2:__"
    assert keyboard.inline_keyboard[-1][0].text == "Resign"


def test_chess_invite_has_rated_and_unrated_modes() -> None:
    message = render_chess_invite_message("@alice", Lang.EN, 50)
    keyboard = render_chess_invite_keyboard(10, Lang.EN)

    assert "Chess invite" in message
    assert "@alice — ▪ Black" in message
    assert "Game value: 50" in message
    assert keyboard.inline_keyboard[0][0].callback_data == "ch:10:join"
    assert keyboard.inline_keyboard[1][0].callback_data == "ch:10:joinu"


def test_chess_callback_parser_reads_square_selection_promotion_and_robot() -> None:
    square = ParsedChessCallback.parse("ch:game-1:sq:e4:e2")
    promotion = ParsedChessCallback.parse("ch:game-1:promo:q")
    robot = ParsedChessCallback.parse("ch:robot:hard")

    assert square is not None
    assert square.action == "sq"
    assert square.value == "e4"
    assert square.selection == "e2"
    assert promotion is not None
    assert promotion.action == "promo"
    assert promotion.value == "q"
    assert robot is not None
    assert robot.action == "robot"
    assert robot.value == "hard"


def test_chess_economy_raises_cost_and_prize() -> None:
    state = ChessState.new(10, 20)

    set_kyzma_prize(state, multiplied_cost(10, CHESS_PVP_COST_MULTIPLIER), FixedRng(), CHESS_PRIZE_MULTIPLIER_FACTOR)

    assert state.kyzma_prize_base == 15
    assert state.kyzma_prize_multiplier == 6
    assert state.kyzma_prize == 90


def test_chess_robot_returns_legal_move() -> None:
    board = chess.Board()
    move = choose_chess_robot_move(board, RobotDifficulty.HARD)

    assert move in board.legal_moves
