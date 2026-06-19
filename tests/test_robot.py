from telegram_board_games_bot.callbacks import apply_robot_turn
from telegram_board_games_bot.games.draughts import BOARD_SIZE, Coord, DraughtsState, GameStatus, Piece, PieceColor, PieceKind
from telegram_board_games_bot.games.robot import RobotDifficulty, choose_robot_move, robot_user_id


def empty_state() -> DraughtsState:
    return DraughtsState(
        board=[[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)],
        turn=PieceColor.BLACK,
        black_user_id=robot_user_id(RobotDifficulty.NORMAL),
        white_user_id=20,
        selected=None,
        must_continue_from=None,
        move_number=1,
        status=GameStatus.IN_PROGRESS,
        winner=None,
        result_reason=None,
        robot_user_id=robot_user_id(RobotDifficulty.NORMAL),
        robot_difficulty=RobotDifficulty.NORMAL.value,
    )


def test_robot_state_metadata_round_trips() -> None:
    state = DraughtsState.new(robot_user_id(RobotDifficulty.HARD), 20)
    state.robot_user_id = robot_user_id(RobotDifficulty.HARD)
    state.robot_difficulty = RobotDifficulty.HARD.value

    restored = DraughtsState.from_json(state.to_json())

    assert restored.robot_user_id == robot_user_id(RobotDifficulty.HARD)
    assert restored.robot_difficulty == "hard"


def test_robot_chooses_available_move() -> None:
    state = empty_state()
    state.board[2][1] = Piece(PieceColor.BLACK, PieceKind.MAN)
    state.board[5][0] = Piece(PieceColor.WHITE, PieceKind.MAN)

    move = choose_robot_move(state, RobotDifficulty.NORMAL)

    assert move is not None
    assert move.from_ == Coord(2, 1)


def test_apply_robot_turn_moves_until_human_turn() -> None:
    state = empty_state()
    state.board[2][1] = Piece(PieceColor.BLACK, PieceKind.MAN)
    state.board[5][0] = Piece(PieceColor.WHITE, PieceKind.MAN)

    applied = apply_robot_turn(state)

    assert len(applied) == 1
    assert state.turn is PieceColor.WHITE
    assert state.current_user_id() == 20

