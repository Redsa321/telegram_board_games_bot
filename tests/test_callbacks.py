import asyncio

from telegram_board_games_bot.callbacks import ParsedCallback, claim_inline_invite, ensure_inline_challenger_user, ensure_inline_chat
from telegram_board_games_bot.commands import GAME_KIND_DRAUGHTS
from telegram_board_games_bot.db import Database, NewGame, UpsertUser
from telegram_board_games_bot.games.draughts import DraughtsState


def test_square_callback_parser_keeps_selection_token() -> None:
    parsed = ParsedCallback.parse("dg:game-1:sq:41:50")

    assert parsed is not None
    assert parsed.game_id == "game-1"
    assert parsed.action == "sq"
    assert parsed.value == "41"
    assert parsed.selection == "50"


def test_robot_callback_parser_reads_difficulty() -> None:
    parsed = ParsedCallback.parse("dg:robot:hard")

    assert parsed is not None
    assert parsed.game_id == "robot"
    assert parsed.action == "robot"
    assert parsed.value == "hard"


def test_parser_reads_invite_modes_and_accept() -> None:
    rated = ParsedCallback.parse("dg:10:join")
    unrated = ParsedCallback.parse("dg:10:joinu")
    accept = ParsedCallback.parse("dg:game-1:accept")

    assert rated is not None
    assert rated.game_id == "10"
    assert rated.action == "join"
    assert unrated is not None
    assert unrated.action == "joinu"
    assert accept is not None
    assert accept.game_id == "game-1"
    assert accept.action == "accept"


def test_claim_inline_invite_allows_known_challenger_without_chosen_result(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))

        assert await claim_inline_invite(database, "inline-1", 10) == "valid"
        database.close()

    asyncio.run(scenario())


def test_claim_inline_invite_allows_missing_chosen_result_and_missing_challenger_row(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()

        assert await claim_inline_invite(database, "inline-1", 10) == "valid"
        database.close()

    asyncio.run(scenario())


def test_claim_inline_invite_rejects_mismatched_stored_invite(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.create_inline_invite("inline-1", 99)

        assert await claim_inline_invite(database, "inline-1", 10) == "mismatch"
        database.close()

    asyncio.run(scenario())


def test_ensure_inline_challenger_user_creates_placeholder(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()

        user = await ensure_inline_challenger_user(database, 10)

        assert user.telegram_user_id == 10
        assert user.first_name == "user 10"
        database.close()

    asyncio.run(scenario())


def test_ensure_inline_chat_allows_inline_game_insert(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.upsert_user(UpsertUser(20, "bob", "Bob", None, "en"))
        await ensure_inline_chat(database)
        state = DraughtsState.new(10, 20)

        game = await database.create_game(NewGame(
            chat_id=0,
            message_id=None,
            inline_message_id="inline-1",
            game_kind=GAME_KIND_DRAUGHTS,
            status="in_progress",
            rated=False,
            state=state,
            current_turn_user_id=state.current_user_id(),
            black_user_id=10,
            white_user_id=20,
        ))

        assert game.chat_id == 0
        assert game.inline_message_id == "inline-1"
        database.close()

    asyncio.run(scenario())
