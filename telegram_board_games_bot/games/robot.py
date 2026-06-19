from __future__ import annotations

import random
from enum import StrEnum

from .draughts import DraughtsMove, DraughtsState, GameStatus, PieceColor, PieceKind


class RobotDifficulty(StrEnum):
    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"


DIFFICULTY_LABELS = {
    RobotDifficulty.EASY: "Easy",
    RobotDifficulty.NORMAL: "Normal",
    RobotDifficulty.HARD: "Hard",
}


ROBOT_USER_IDS = {
    RobotDifficulty.EASY: -1001,
    RobotDifficulty.NORMAL: -1002,
    RobotDifficulty.HARD: -1003,
}


def parse_difficulty(value: str) -> RobotDifficulty | None:
    try:
        return RobotDifficulty(value)
    except ValueError:
        return None


def robot_user_id(difficulty: RobotDifficulty) -> int:
    return ROBOT_USER_IDS[difficulty]


def robot_name(difficulty: RobotDifficulty) -> str:
    return f"Robot ({DIFFICULTY_LABELS[difficulty]})"


def choose_robot_move(state: DraughtsState, difficulty: RobotDifficulty) -> DraughtsMove | None:
    legal_moves = state.legal_moves()
    if not legal_moves:
        return None
    if difficulty is RobotDifficulty.EASY:
        return random.choice(legal_moves)
    if difficulty is RobotDifficulty.NORMAL:
        return max(legal_moves, key=lambda move: normal_move_score(state, move) + random.random() * 0.25)
    return max(legal_moves, key=lambda move: hard_move_score(state, move))


def normal_move_score(state: DraughtsState, move: DraughtsMove) -> float:
    simulated = clone_state(state)
    result = simulated.apply_move(move)
    score = len(result.captured) * 10
    if result.promoted:
        score += 4
    if result.game_finished:
        score += 1000
    return score


def hard_move_score(state: DraughtsState, move: DraughtsMove) -> float:
    robot_id = state.current_user_id()
    simulated = clone_state(state)
    result = simulated.apply_move(move)
    robot_color = simulated.user_color(robot_id)
    if robot_color is None:
        return -10_000
    if simulated.status is GameStatus.FINISHED:
        return 10_000 if simulated.winner_user_id() == robot_id else -10_000

    score = board_score(simulated, robot_color)
    score += len(result.captured) * 20
    score += 8 if result.promoted else 0
    score -= opponent_capture_pressure(simulated, robot_color) * 12
    score += len(simulated.legal_moves_for_piece(move.sequence[-1])) if not result.turn_ended else 0
    return score


def board_score(state: DraughtsState, robot_color: PieceColor) -> float:
    score = 0.0
    for row in state.board:
        for piece in row:
            if piece is None:
                continue
            value = 5 if piece.kind is PieceKind.KING else 3
            score += value if piece.color is robot_color else -value
    current_turn = state.turn
    state.turn = robot_color
    own_mobility = len(state.legal_moves())
    state.turn = robot_color.opponent
    opponent_mobility = len(state.legal_moves())
    state.turn = current_turn
    return score * 10 + own_mobility - opponent_mobility


def opponent_capture_pressure(state: DraughtsState, robot_color: PieceColor) -> int:
    current_turn = state.turn
    state.turn = robot_color.opponent
    captures = sum(1 for move in state.legal_moves() if state.captured_coord(move.from_, move.sequence[0], state.piece_at(move.from_)) is not None)
    state.turn = current_turn
    return captures


def clone_state(state: DraughtsState) -> DraughtsState:
    return DraughtsState.from_json(state.to_json())

