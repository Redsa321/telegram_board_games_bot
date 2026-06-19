from __future__ import annotations

import random

import chess

from .robot import DIFFICULTY_LABELS, RobotDifficulty


CHESS_ROBOT_USER_IDS = {
    RobotDifficulty.EASY: -2001,
    RobotDifficulty.NORMAL: -2002,
    RobotDifficulty.HARD: -2003,
}


PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def chess_robot_user_id(difficulty: RobotDifficulty) -> int:
    return CHESS_ROBOT_USER_IDS[difficulty]


def chess_robot_name(difficulty: RobotDifficulty) -> str:
    return f"Chess Robot ({DIFFICULTY_LABELS[difficulty]})"


def choose_chess_robot_move(board: chess.Board, difficulty: RobotDifficulty) -> chess.Move | None:
    legal_moves = list(board.legal_moves)
    if not legal_moves:
        return None
    if difficulty is RobotDifficulty.EASY:
        return random.choice(legal_moves)
    if difficulty is RobotDifficulty.NORMAL:
        return max(legal_moves, key=lambda move: normal_move_score(board, move) + random.random() * 0.2)
    return max(legal_moves, key=lambda move: hard_move_score(board, move))


def normal_move_score(board: chess.Board, move: chess.Move) -> float:
    score = 0.0
    if board.is_capture(move):
        captured = board.piece_at(move.to_square)
        if captured:
            score += PIECE_VALUES[captured.piece_type] / 100
    if move.promotion:
        score += PIECE_VALUES[move.promotion] / 100
    simulated = board.copy(stack=False)
    simulated.push(move)
    if simulated.is_checkmate():
        score += 1000
    elif simulated.is_check():
        score += 3
    return score


def hard_move_score(board: chess.Board, move: chess.Move) -> float:
    robot_color = board.turn
    simulated = board.copy(stack=False)
    simulated.push(move)
    outcome = simulated.outcome(claim_draw=True)
    if outcome is not None:
        if outcome.winner is robot_color:
            return 100_000
        if outcome.winner is None:
            return 0
        return -100_000
    return material_score(simulated, robot_color) + mobility_score(simulated, robot_color) + normal_move_score(board, move)


def material_score(board: chess.Board, color: bool) -> float:
    score = 0.0
    for piece_type, value in PIECE_VALUES.items():
        score += len(board.pieces(piece_type, color)) * value
        score -= len(board.pieces(piece_type, not color)) * value
    return score / 100


def mobility_score(board: chess.Board, color: bool) -> float:
    turn = board.turn
    board.turn = color
    own = board.legal_moves.count()
    board.turn = not color
    opponent = board.legal_moves.count()
    board.turn = turn
    return (own - opponent) * 0.05
