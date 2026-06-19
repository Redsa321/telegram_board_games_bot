from telegram_board_games_bot.games.draughts import (
    BOARD_SIZE,
    Coord,
    DraughtsMove,
    DraughtsState,
    GameStatus,
    Piece,
    PieceColor,
    PieceKind,
    move_to_id,
    parse_move_id,
)


BLACK_USER = 10
WHITE_USER = 20


def c(row: int, col: int) -> Coord:
    return Coord(row, col)


def mv(from_: Coord, sequence: list[Coord]) -> DraughtsMove:
    return DraughtsMove(from_, sequence)


def empty_state() -> DraughtsState:
    return DraughtsState(
        board=[[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)],
        turn=PieceColor.BLACK,
        black_user_id=BLACK_USER,
        white_user_id=WHITE_USER,
        selected=None,
        must_continue_from=None,
        move_number=1,
        status=GameStatus.IN_PROGRESS,
        winner=None,
        result_reason=None,
    )


def place_man(state: DraughtsState, coord: Coord, color: PieceColor) -> None:
    state.board[coord.row][coord.col] = Piece(color, PieceKind.MAN)


def place_king(state: DraughtsState, coord: Coord, color: PieceColor) -> None:
    state.board[coord.row][coord.col] = Piece(color, PieceKind.KING)


def test_initial_board_has_12_black_and_12_white_pieces() -> None:
    state = DraughtsState.new(BLACK_USER, WHITE_USER)
    assert sum(1 for row in state.board for piece in row if piece and piece.color is PieceColor.BLACK) == 12
    assert sum(1 for row in state.board for piece in row if piece and piece.color is PieceColor.WHITE) == 12
    assert state.turn is PieceColor.WHITE
    assert state.current_user_id() == WHITE_USER


def test_normal_move_works() -> None:
    state = DraughtsState.new(BLACK_USER, WHITE_USER)
    result = state.apply_move(mv(c(5, 0), [c(4, 1)]))
    assert state.board[5][0] is None
    assert state.board[4][1] == Piece(PieceColor.WHITE, PieceKind.MAN)
    assert result.turn_ended
    assert state.turn is PieceColor.BLACK


def test_mandatory_capture_and_multi_capture_continue() -> None:
    state = empty_state()
    place_man(state, c(2, 1), PieceColor.BLACK)
    place_man(state, c(3, 2), PieceColor.WHITE)
    place_man(state, c(5, 4), PieceColor.WHITE)

    first = state.apply_move(mv(c(2, 1), [c(4, 3)]))

    assert not first.turn_ended
    assert state.must_continue_from == c(4, 3)
    assert state.captured_this_turn == [c(3, 2)]
    assert state.legal_moves() == [mv(c(4, 3), [c(6, 5)])]

    second = state.apply_move(mv(c(4, 3), [c(6, 5)]))
    assert second.turn_ended
    assert second.captured == [c(5, 4)]
    assert state.turn is PieceColor.WHITE


def test_flying_king_capture_can_require_continuation() -> None:
    state = empty_state()
    place_king(state, c(5, 0), PieceColor.BLACK)
    place_man(state, c(3, 2), PieceColor.WHITE)
    place_man(state, c(3, 6), PieceColor.WHITE)

    result = state.apply_move(mv(c(5, 0), [c(1, 4)]))

    assert not result.turn_ended
    assert state.must_continue_from == c(1, 4)
    assert state.legal_moves() == [mv(c(1, 4), [c(4, 7)])]


def test_game_ends_when_current_player_has_no_legal_moves() -> None:
    state = empty_state()
    place_man(state, c(5, 0), PieceColor.BLACK)
    place_man(state, c(5, 2), PieceColor.BLACK)
    place_man(state, c(7, 0), PieceColor.WHITE)

    result = state.apply_move(mv(c(5, 0), [c(6, 1)]))

    assert result.game_finished
    assert state.status is GameStatus.FINISHED
    assert state.winner is PieceColor.BLACK
    assert state.winner_user_id() == BLACK_USER
    assert state.result_reason == "opponent has no legal moves"


def test_move_id_round_trips_and_state_json_uses_rust_names() -> None:
    original = mv(c(2, 1), [c(4, 3), c(6, 5)])
    encoded = move_to_id(original)
    restored = DraughtsState.from_json(DraughtsState.new(BLACK_USER, WHITE_USER).to_json())

    assert encoded == "21>43>65"
    assert parse_move_id(encoded) == original
    assert restored.turn is PieceColor.WHITE
    assert "from" in original.to_json()

