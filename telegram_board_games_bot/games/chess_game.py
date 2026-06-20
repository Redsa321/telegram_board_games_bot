from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import chess


class ChessStatus(StrEnum):
    CONFIRMING = "confirming"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


@dataclass
class ChessState:
    fen: str
    white_user_id: int
    black_user_id: int
    status: ChessStatus
    selected_square: str | None = None
    promotion_from: str | None = None
    promotion_to: str | None = None
    winner_user_id_value: int | None = None
    result_reason: str | None = None
    accepted_user_ids: list[int] = field(default_factory=list)
    robot_user_id: int | None = None
    robot_difficulty: str | None = None
    kyzma_prize_base: int | None = None
    kyzma_prize_multiplier: int | None = None
    kyzma_prize: int | None = None
    global_game: bool = False
    anonymous_user_ids: list[int] = field(default_factory=list)
    global_rank: str | None = None
    move_timeout_seconds: int | None = None
    turn_started_at: str | None = None
    timeout_stage: str | None = None
    timeout_proposer_user_id: int | None = None
    timeout_accepted_user_ids: list[int] = field(default_factory=list)

    @classmethod
    def new(cls, white_user_id: int, black_user_id: int) -> "ChessState":
        return cls(
            fen=chess.Board().fen(),
            white_user_id=white_user_id,
            black_user_id=black_user_id,
            status=ChessStatus.IN_PROGRESS,
        )

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "ChessState":
        return cls(
            fen=value["fen"],
            white_user_id=int(value["white_user_id"]),
            black_user_id=int(value["black_user_id"]),
            status=ChessStatus(value["status"]),
            selected_square=value.get("selected_square"),
            promotion_from=value.get("promotion_from"),
            promotion_to=value.get("promotion_to"),
            winner_user_id_value=value.get("winner_user_id"),
            result_reason=value.get("result_reason"),
            accepted_user_ids=[int(user_id) for user_id in value.get("accepted_user_ids", [])],
            robot_user_id=value.get("robot_user_id"),
            robot_difficulty=value.get("robot_difficulty"),
            kyzma_prize_base=value.get("kyzma_prize_base"),
            kyzma_prize_multiplier=value.get("kyzma_prize_multiplier"),
            kyzma_prize=value.get("kyzma_prize"),
            global_game=bool(value.get("global_game", False)),
            anonymous_user_ids=[int(user_id) for user_id in value.get("anonymous_user_ids", [])],
            global_rank=value.get("global_rank"),
            move_timeout_seconds=value.get("move_timeout_seconds"),
            turn_started_at=value.get("turn_started_at"),
            timeout_stage=value.get("timeout_stage"),
            timeout_proposer_user_id=value.get("timeout_proposer_user_id"),
            timeout_accepted_user_ids=[int(user_id) for user_id in value.get("timeout_accepted_user_ids", [])],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "fen": self.fen,
            "white_user_id": self.white_user_id,
            "black_user_id": self.black_user_id,
            "status": self.status.value,
            "selected_square": self.selected_square,
            "promotion_from": self.promotion_from,
            "promotion_to": self.promotion_to,
            "winner_user_id": self.winner_user_id_value,
            "result_reason": self.result_reason,
            "accepted_user_ids": self.accepted_user_ids,
            "robot_user_id": self.robot_user_id,
            "robot_difficulty": self.robot_difficulty,
            "kyzma_prize_base": self.kyzma_prize_base,
            "kyzma_prize_multiplier": self.kyzma_prize_multiplier,
            "kyzma_prize": self.kyzma_prize,
            "global_game": self.global_game,
            "anonymous_user_ids": self.anonymous_user_ids,
            "global_rank": self.global_rank,
            "move_timeout_seconds": self.move_timeout_seconds,
            "turn_started_at": self.turn_started_at,
            "timeout_stage": self.timeout_stage,
            "timeout_proposer_user_id": self.timeout_proposer_user_id,
            "timeout_accepted_user_ids": self.timeout_accepted_user_ids,
        }

    def board(self) -> chess.Board:
        return chess.Board(self.fen)

    def current_user_id(self) -> int:
        return self.white_user_id if self.board().turn == chess.WHITE else self.black_user_id

    def user_color(self, user_id: int) -> bool | None:
        if user_id == self.white_user_id:
            return chess.WHITE
        if user_id == self.black_user_id:
            return chess.BLACK
        return None

    def winner_user_id(self) -> int | None:
        return self.winner_user_id_value

    def clear_interaction(self) -> None:
        self.selected_square = None
        self.promotion_from = None
        self.promotion_to = None

    def select_square(self, square_name: str) -> None:
        self.selected_square = square_name
        self.promotion_from = None
        self.promotion_to = None

    def set_promotion_pending(self, from_square: str, to_square: str) -> None:
        self.selected_square = from_square
        self.promotion_from = from_square
        self.promotion_to = to_square

    def legal_move(self, from_square: str, to_square: str, promotion: int | None = None) -> chess.Move | None:
        board = self.board()
        move = chess.Move(chess.parse_square(from_square), chess.parse_square(to_square), promotion=promotion)
        return move if move in board.legal_moves else None

    def promotion_options(self, from_square: str, to_square: str) -> list[int]:
        return [
            promotion
            for promotion in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)
            if self.legal_move(from_square, to_square, promotion) is not None
        ]

    def apply_move(self, move: chess.Move) -> None:
        board = self.board()
        board.push(move)
        self.fen = board.fen()
        self.clear_interaction()
        self.finish_if_game_over(board)

    def finish_if_game_over(self, board: chess.Board | None = None) -> None:
        board = board or self.board()
        outcome = board.outcome(claim_draw=True)
        if outcome is None:
            return
        self.status = ChessStatus.FINISHED
        if outcome.winner is chess.WHITE:
            self.winner_user_id_value = self.white_user_id
        elif outcome.winner is chess.BLACK:
            self.winner_user_id_value = self.black_user_id
        else:
            self.winner_user_id_value = None
        self.result_reason = outcome.termination.name.lower().replace("_", " ")
        self.clear_interaction()

    def finish_with_resignation(self, resigning_user_id: int) -> None:
        self.status = ChessStatus.FINISHED
        self.winner_user_id_value = self.black_user_id if resigning_user_id == self.white_user_id else self.white_user_id
        self.result_reason = "resignation"
        self.clear_interaction()


def valid_square_name(value: str) -> bool:
    try:
        chess.parse_square(value)
    except ValueError:
        return False
    return True


def square_name(square: int) -> str:
    return chess.square_name(square)
