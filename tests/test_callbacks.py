import asyncio
from types import SimpleNamespace

from telegram import User

from telegram_board_games_bot.callbacks import (
    MessageTarget,
    ParsedCallback,
    claim_inline_invite,
    ensure_inline_challenger_user,
    ensure_inline_chat,
    handle_square_callback,
)
from telegram_board_games_bot.commands import GAME_KIND_DRAUGHTS
from telegram_board_games_bot.db import Database, NewGame, UpsertChat, UpsertUser
from telegram_board_games_bot.games.draughts import Coord, DraughtsState


class FakeBot:
    def __init__(self) -> None:
        self.edits = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


class FakeQuery:
    def __init__(self, user_id: int) -> None:
        self.from_user = User(user_id, f"User {user_id}", False, language_code="en")
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


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


def test_piece_selection_is_persisted_before_board_edit(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(100, "group", "group"))
        await database.upsert_user(UpsertUser(10, "black", "Black", None, "en"))
        await database.upsert_user(UpsertUser(20, "white", "White", None, "en"))
        state = DraughtsState.new(10, 20)
        game = await database.create_game(NewGame(
            chat_id=100,
            message_id=55,
            inline_message_id=None,
            game_kind=GAME_KIND_DRAUGHTS,
            status=state.status.value,
            rated=True,
            state=state,
            current_turn_user_id=state.current_user_id(),
            black_user_id=10,
            white_user_id=20,
        ))
        bot = FakeBot()
        context = SimpleNamespace(bot=bot)

        await handle_square_callback(
            context,
            database,
            FakeQuery(20),
            MessageTarget(chat_id=100, message_id=55),
            game.id,
            Coord(5, 0),
        )

        restored = DraughtsState.from_json((await database.get_game(game.id)).state)
        assert restored.selected == Coord(5, 0)
        assert bot.edits
        database.close()

    asyncio.run(scenario())


def test_wrong_turn_tap_refreshes_stale_board(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(100, "group", "group"))
        await database.upsert_user(UpsertUser(10, "black", "Black", None, "en"))
        await database.upsert_user(UpsertUser(20, "white", "White", None, "en"))
        state = DraughtsState.new(10, 20)
        game = await database.create_game(NewGame(
            chat_id=100,
            message_id=55,
            inline_message_id=None,
            game_kind=GAME_KIND_DRAUGHTS,
            status=state.status.value,
            rated=True,
            state=state,
            current_turn_user_id=state.current_user_id(),
            black_user_id=10,
            white_user_id=20,
        ))
        bot = FakeBot()
        query = FakeQuery(10)

        await handle_square_callback(
            SimpleNamespace(bot=bot),
            database,
            query,
            MessageTarget(chat_id=100, message_id=55),
            game.id,
            Coord(2, 1),
        )

        assert query.answers
        assert bot.edits
        assert "Turn: @white" in bot.edits[-1]["text"]
        database.close()

    asyncio.run(scenario())
