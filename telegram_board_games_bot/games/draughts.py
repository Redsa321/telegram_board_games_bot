from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


BOARD_SIZE = 8


class PieceColor(StrEnum):
    BLACK = "black"
    WHITE = "white"

    @property
    def opponent(self) -> "PieceColor":
        return PieceColor.WHITE if self is PieceColor.BLACK else PieceColor.BLACK

    @property
    def forward_row_delta(self) -> int:
        return 1 if self is PieceColor.BLACK else -1


class PieceKind(StrEnum):
    MAN = "man"
    KING = "king"


class GameStatus(StrEnum):
    CONFIRMING = "confirming"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


@dataclass(frozen=True)
class Piece:
    color: PieceColor
    kind: PieceKind

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "Piece":
        return cls(color=PieceColor(value["color"]), kind=PieceKind(value["kind"]))

    def to_json(self) -> dict[str, str]:
        return {"color": self.color.value, "kind": self.kind.value}


@dataclass(frozen=True)
class Coord:
    row: int
    col: int

    @classmethod
    def from_json(cls, value: dict[str, Any] | None) -> "Coord | None":
        if value is None:
            return None
        return cls(row=int(value["row"]), col=int(value["col"]))

    def to_json(self) -> dict[str, int]:
        return {"row": self.row, "col": self.col}


@dataclass(frozen=True)
class DraughtsMove:
    from_: Coord
    sequence: list[Coord]

    @classmethod
    def from_json(cls, value: dict[str, Any] | None) -> "DraughtsMove | None":
        if value is None:
            return None
        return cls(
            from_=Coord.from_json(value["from"]),
            sequence=[Coord.from_json(coord) for coord in value["sequence"]],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "from": self.from_.to_json(),
            "sequence": [coord.to_json() for coord in self.sequence],
        }


@dataclass
class ApplyMoveResult:
    captured: list[Coord]
    promoted: bool
    turn_ended: bool
    game_finished: bool
    winner: PieceColor | None


class DraughtsError(ValueError):
    pass


@dataclass
class DraughtsState:
    board: list[list[Piece | None]]
    turn: PieceColor
    black_user_id: int
    white_user_id: int
    selected: Coord | None
    must_continue_from: Coord | None
    move_number: int
    status: GameStatus
    winner: PieceColor | None
    result_reason: str | None
    captured_this_turn: list[Coord] = field(default_factory=list)
    last_move: DraughtsMove | None = None
    rematch_requested_by: int | None = None
    robot_user_id: int | None = None
    robot_difficulty: str | None = None
    kyzma_prize_base: int | None = None
    kyzma_prize_multiplier: int | None = None
    kyzma_prize: int | None = None
    accepted_user_ids: list[int] = field(default_factory=list)

    @classmethod
    def new(cls, black_user_id: int, white_user_id: int) -> "DraughtsState":
        board: list[list[Piece | None]] = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                coord = Coord(row, col)
                if not is_playable_square(coord):
                    continue
                if row <= 2:
                    board[row][col] = Piece(PieceColor.BLACK, PieceKind.MAN)
                elif row >= 5:
                    board[row][col] = Piece(PieceColor.WHITE, PieceKind.MAN)
        return cls(
            board=board,
            turn=PieceColor.WHITE,
            black_user_id=black_user_id,
            white_user_id=white_user_id,
            selected=None,
            must_continue_from=None,
            move_number=1,
            status=GameStatus.IN_PROGRESS,
            winner=None,
            result_reason=None,
        )

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "DraughtsState":
        return cls(
            board=[
                [Piece.from_json(piece) if piece is not None else None for piece in row]
                for row in value["board"]
            ],
            turn=PieceColor(value["turn"]),
            black_user_id=int(value["black_user_id"]),
            white_user_id=int(value["white_user_id"]),
            selected=Coord.from_json(value.get("selected")),
            must_continue_from=Coord.from_json(value.get("must_continue_from")),
            move_number=int(value["move_number"]),
            status=GameStatus(value["status"]),
            winner=PieceColor(value["winner"]) if value.get("winner") else None,
            result_reason=value.get("result_reason"),
            captured_this_turn=[Coord.from_json(coord) for coord in value.get("captured_this_turn", [])],
            last_move=DraughtsMove.from_json(value.get("last_move")),
            rematch_requested_by=value.get("rematch_requested_by"),
            robot_user_id=value.get("robot_user_id"),
            robot_difficulty=value.get("robot_difficulty"),
            kyzma_prize_base=value.get("kyzma_prize_base"),
            kyzma_prize_multiplier=value.get("kyzma_prize_multiplier"),
            kyzma_prize=value.get("kyzma_prize"),
            accepted_user_ids=[int(user_id) for user_id in value.get("accepted_user_ids", [])],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "board": [
                [piece.to_json() if piece is not None else None for piece in row]
                for row in self.board
            ],
            "turn": self.turn.value,
            "black_user_id": self.black_user_id,
            "white_user_id": self.white_user_id,
            "selected": self.selected.to_json() if self.selected else None,
            "must_continue_from": self.must_continue_from.to_json() if self.must_continue_from else None,
            "move_number": self.move_number,
            "status": self.status.value,
            "winner": self.winner.value if self.winner else None,
            "result_reason": self.result_reason,
            "captured_this_turn": [coord.to_json() for coord in self.captured_this_turn],
            "last_move": self.last_move.to_json() if self.last_move else None,
            "rematch_requested_by": self.rematch_requested_by,
            "robot_user_id": self.robot_user_id,
            "robot_difficulty": self.robot_difficulty,
            "kyzma_prize_base": self.kyzma_prize_base,
            "kyzma_prize_multiplier": self.kyzma_prize_multiplier,
            "kyzma_prize": self.kyzma_prize,
            "accepted_user_ids": self.accepted_user_ids,
        }

    def legal_moves(self) -> list[DraughtsMove]:
        if self.status is not GameStatus.IN_PROGRESS:
            return []
        if self.must_continue_from:
            return self.capture_moves_for_piece(self.must_continue_from)
        captures = self.capture_moves_for_current_player()
        if captures:
            return captures
        moves: list[DraughtsMove] = []
        for coord in self.coords_for_current_player():
            moves.extend(self.simple_moves_for_piece(coord))
        return moves

    def legal_moves_for_piece(self, from_: Coord) -> list[DraughtsMove]:
        if self.status is not GameStatus.IN_PROGRESS or not self.is_current_players_piece(from_):
            return []
        if self.must_continue_from:
            return self.capture_moves_for_piece(from_) if self.must_continue_from == from_ else []
        captures = self.capture_moves_for_piece(from_)
        if captures:
            return captures
        return [] if self.has_capture_for_current_player() else self.simple_moves_for_piece(from_)

    def has_forced_capture(self) -> bool:
        if self.status is not GameStatus.IN_PROGRESS:
            return False
        if self.must_continue_from:
            return bool(self.capture_moves_for_piece(self.must_continue_from))
        return self.has_capture_for_current_player()

    def apply_move(self, move: DraughtsMove) -> ApplyMoveResult:
        if self.status is not GameStatus.IN_PROGRESS:
            raise DraughtsError("the game is not in progress")
        if not move.sequence:
            raise DraughtsError("move sequence must contain at least one destination")
        if not is_valid_coord(move.from_) or not is_playable_square(move.from_):
            raise DraughtsError("invalid source coordinate")
        if self.must_continue_from and self.must_continue_from != move.from_:
            raise DraughtsError("the current player must continue capturing")

        original_from = move.from_
        from_ = move.from_
        captured: list[Coord] = []
        promoted = False
        turn_ended = False

        for index, to in enumerate(move.sequence):
            if not is_valid_coord(to) or not is_playable_square(to):
                raise DraughtsError("invalid destination coordinate")
            legal_step = any(
                legal.from_ == from_ and legal.sequence == [to]
                for legal in self.legal_moves()
            )
            if not legal_step:
                raise DraughtsError("the selected move is not legal")

            piece = self.piece_at(from_)
            if piece is None:
                raise DraughtsError("there is no piece at coordinate")
            captured_coord = self.captured_coord(from_, to, piece)
            self.set_piece(from_, None)
            self.set_piece(to, piece)

            if captured_coord:
                self.set_piece(captured_coord, None)
                captured.append(captured_coord)
                self.captured_this_turn.append(captured_coord)

            if self.promote_if_needed(to):
                promoted = True

            self.selected = None
            from_ = to

            must_stop_for_promotion = promoted and captured_coord is not None and piece.kind is PieceKind.MAN
            further_captures = (
                self.capture_moves_for_piece(to)
                if captured_coord is not None and not must_stop_for_promotion
                else []
            )
            if further_captures:
                self.must_continue_from = to
                if index + 1 == len(move.sequence):
                    self.last_move = DraughtsMove(original_from, move.sequence[: index + 1])
                    return ApplyMoveResult(captured, promoted, False, False, None)
            else:
                self.end_turn()
                turn_ended = True

        if not turn_ended:
            self.end_turn()
            turn_ended = True
        self.last_move = move
        return ApplyMoveResult(captured, promoted, turn_ended, self.status is GameStatus.FINISHED, self.winner)

    def current_user_id(self) -> int:
        return self.black_user_id if self.turn is PieceColor.BLACK else self.white_user_id

    def user_color(self, user_id: int) -> PieceColor | None:
        if user_id == self.black_user_id:
            return PieceColor.BLACK
        if user_id == self.white_user_id:
            return PieceColor.WHITE
        return None

    def winner_user_id(self) -> int | None:
        if self.winner is PieceColor.BLACK:
            return self.black_user_id
        if self.winner is PieceColor.WHITE:
            return self.white_user_id
        return None

    def end_turn(self) -> None:
        self.must_continue_from = None
        self.captured_this_turn.clear()
        self.turn = self.turn.opponent
        self.move_number += 1
        self.finish_if_current_player_is_stuck()

    def finish_if_current_player_is_stuck(self) -> None:
        current_piece_count = sum(
            1 for row in self.board for piece in row if piece is not None and piece.color is self.turn
        )
        if current_piece_count == 0:
            self.finish_with_winner(self.turn.opponent, "opponent has no pieces")
        elif not self.legal_moves():
            self.finish_with_winner(self.turn.opponent, "opponent has no legal moves")

    def finish_with_winner(self, winner: PieceColor, reason: str) -> None:
        self.status = GameStatus.FINISHED
        self.winner = winner
        self.result_reason = reason
        self.selected = None
        self.must_continue_from = None
        self.captured_this_turn.clear()

    def capture_moves_for_current_player(self) -> list[DraughtsMove]:
        moves: list[DraughtsMove] = []
        for coord in self.coords_for_current_player():
            moves.extend(self.capture_moves_for_piece(coord))
        return moves

    def has_capture_for_current_player(self) -> bool:
        return any(self.capture_moves_for_piece(coord) for coord in self.coords_for_current_player())

    def coords_for_current_player(self) -> list[Coord]:
        return [
            Coord(row, col)
            for row in range(BOARD_SIZE)
            for col in range(BOARD_SIZE)
            if self.is_current_players_piece(Coord(row, col))
        ]

    def simple_moves_for_piece(self, from_: Coord) -> list[DraughtsMove]:
        piece = self.piece_at(from_)
        if piece is None:
            return []
        if piece.kind is PieceKind.MAN:
            moves = []
            for row_delta, col_delta in self.move_directions_for(piece):
                to = offset_coord(from_, row_delta, col_delta)
                if to and is_playable_square(to) and self.piece_at(to) is None:
                    moves.append(DraughtsMove(from_, [to]))
            return moves
        return self.sliding_moves_for_king(from_)

    def capture_moves_for_piece(self, from_: Coord) -> list[DraughtsMove]:
        piece = self.piece_at(from_)
        if piece is None or piece.color is not self.turn:
            return []
        if piece.kind is PieceKind.MAN:
            return self.short_capture_moves_for_man(from_, piece)
        return self.flying_capture_moves_for_king(from_, piece)

    def short_capture_moves_for_man(self, from_: Coord, piece: Piece) -> list[DraughtsMove]:
        moves = []
        for row_delta, col_delta in self.capture_directions_for(piece):
            jumped = offset_coord(from_, row_delta, col_delta)
            to = offset_coord(from_, row_delta * 2, col_delta * 2)
            if (
                jumped
                and to
                and is_playable_square(to)
                and self.piece_at(to) is None
                and (jumped_piece := self.piece_at(jumped)) is not None
                and jumped_piece.color is piece.color.opponent
            ):
                moves.append(DraughtsMove(from_, [to]))
        return moves

    def flying_capture_moves_for_king(self, from_: Coord, piece: Piece) -> list[DraughtsMove]:
        moves: list[DraughtsMove] = []
        for row_delta, col_delta in self.capture_directions_for(piece):
            next_coord = offset_coord(from_, row_delta, col_delta)
            jumped_opponent: Coord | None = None
            while next_coord:
                next_piece = self.piece_at(next_coord)
                if next_piece is None and jumped_opponent is not None:
                    moves.append(DraughtsMove(from_, [next_coord]))
                elif next_piece is None:
                    pass
                elif next_piece.color is piece.color.opponent and jumped_opponent is None:
                    jumped_opponent = next_coord
                else:
                    break
                next_coord = offset_coord(next_coord, row_delta, col_delta)
        return moves

    def sliding_moves_for_king(self, from_: Coord) -> list[DraughtsMove]:
        moves: list[DraughtsMove] = []
        for row_delta, col_delta in [(1, -1), (1, 1), (-1, -1), (-1, 1)]:
            next_coord = offset_coord(from_, row_delta, col_delta)
            while next_coord:
                if self.piece_at(next_coord) is not None:
                    break
                moves.append(DraughtsMove(from_, [next_coord]))
                next_coord = offset_coord(next_coord, row_delta, col_delta)
        return moves

    def move_directions_for(self, piece: Piece) -> list[tuple[int, int]]:
        if piece.kind is PieceKind.MAN:
            return [(piece.color.forward_row_delta, -1), (piece.color.forward_row_delta, 1)]
        return [(1, -1), (1, 1), (-1, -1), (-1, 1)]

    def capture_directions_for(self, piece: Piece) -> list[tuple[int, int]]:
        return [(1, -1), (1, 1), (-1, -1), (-1, 1)]

    def promote_if_needed(self, coord: Coord) -> bool:
        piece = self.piece_at(coord)
        if piece is None or piece.kind is PieceKind.KING:
            return False
        promotion_row = 7 if piece.color is PieceColor.BLACK else 0
        if coord.row != promotion_row:
            return False
        self.set_piece(coord, Piece(piece.color, PieceKind.KING))
        return True

    def is_current_players_piece(self, coord: Coord) -> bool:
        piece = self.piece_at(coord)
        return piece is not None and piece.color is self.turn

    def piece_at(self, coord: Coord) -> Piece | None:
        if not is_valid_coord(coord):
            return None
        return self.board[coord.row][coord.col]

    def set_piece(self, coord: Coord, piece: Piece | None) -> None:
        self.board[coord.row][coord.col] = piece

    def captured_coord(self, from_: Coord, to: Coord, piece: Piece) -> Coord | None:
        if piece.kind is PieceKind.MAN:
            return short_capture_coord(from_, to)
        return self.flying_capture_coord(from_, to, piece)

    def flying_capture_coord(self, from_: Coord, to: Coord, piece: Piece) -> Coord | None:
        row_delta = to.row - from_.row
        col_delta = to.col - from_.col
        if abs(row_delta) != abs(col_delta) or abs(row_delta) < 2:
            return None
        row_step = sign(row_delta)
        col_step = sign(col_delta)
        next_coord = offset_coord(from_, row_step, col_step)
        captured: Coord | None = None
        while next_coord:
            if next_coord == to:
                break
            path_piece = self.piece_at(next_coord)
            if path_piece is not None:
                if path_piece.color is not piece.color.opponent or captured is not None:
                    return None
                captured = next_coord
            next_coord = offset_coord(next_coord, row_step, col_step)
        return captured


def is_playable_square(coord: Coord) -> bool:
    return is_valid_coord(coord) and (coord.row + coord.col) % 2 == 1


def coord_to_id(coord: Coord) -> str:
    return f"{coord.row}{coord.col}"


def move_to_id(move: DraughtsMove) -> str:
    return ">".join(coord_to_id(coord) for coord in [move.from_, *move.sequence])


def parse_move_id(move_id: str) -> DraughtsMove:
    coords = [parse_coord_id(part) for part in move_id.split(">")]
    if len(coords) < 2:
        raise DraughtsError("move id must contain at least a source and destination")
    return DraughtsMove(coords[0], coords[1:])


def parse_coord_id(coord_id: str) -> Coord:
    if len(coord_id) != 2 or not coord_id.isdigit():
        raise DraughtsError("invalid move coordinate in callback data")
    coord = Coord(int(coord_id[0]), int(coord_id[1]))
    if not is_valid_coord(coord):
        raise DraughtsError("invalid move coordinate in callback data")
    return coord


def is_valid_coord(coord: Coord) -> bool:
    return 0 <= coord.row < BOARD_SIZE and 0 <= coord.col < BOARD_SIZE


def offset_coord(coord: Coord, row_delta: int, col_delta: int) -> Coord | None:
    row = coord.row + row_delta
    col = coord.col + col_delta
    if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE:
        return Coord(row, col)
    return None


def short_capture_coord(from_: Coord, to: Coord) -> Coord | None:
    row_delta = to.row - from_.row
    col_delta = to.col - from_.col
    if abs(row_delta) == 2 and abs(col_delta) == 2:
        return Coord((from_.row + to.row) // 2, (from_.col + to.col) // 2)
    return None


def sign(value: int) -> int:
    return (value > 0) - (value < 0)
