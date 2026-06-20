import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from telegram_board_games_bot.callbacks import MessageTarget, finish_rated_game, play_move_and_update
from telegram_board_games_bot.commands import GAME_KIND_CHESS, GAME_KIND_DRAUGHTS
from telegram_board_games_bot.db import Database, GameOutcome, MatchmakingEntry, UpsertChat, UpsertUser
from telegram_board_games_bot.games.chess_game import ChessState, ChessStatus
from telegram_board_games_bot.games.draughts import DraughtsState, GameStatus, PieceColor
from telegram_board_games_bot.global_matchmaking import (
    accept_global_timeout,
    cancel_global_timeout,
    create_global_match,
    default_move_timeout,
    expire_overdue_global_games,
    expire_stale_matchmaking_entries,
    expire_stale_timeout_setups,
    global_game_stats_text,
    global_state_update,
    match_rank_and_cost,
    parse_global_timeout_callback,
    parse_matchmaking_callback,
    propose_global_timeout,
    rank_for_rating,
    rank_game_cost,
    request_global_timeout_change,
)


class FakeBot:
    def __init__(self) -> None:
        self.edits = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


def entry(
    user_id: int,
    rating: int = 1000,
    joined_at: str | None = None,
    anonymous: bool = False,
    game_kind: str = GAME_KIND_DRAUGHTS,
    rated: bool = True,
) -> MatchmakingEntry:
    return MatchmakingEntry(
        user_id=user_id,
        chat_id=user_id,
        message_id=user_id * 10,
        game_kind=game_kind,
        rated=rated,
        anonymous=anonymous,
        rating=rating,
        joined_at=joined_at or datetime.now(UTC).isoformat(),
    )


def test_rank_boundaries_and_fixed_costs() -> None:
    assert rank_for_rating(899).name == "Bronze"
    assert rank_for_rating(900).name == "Silver"
    assert rank_for_rating(1099).name == "Silver"
    assert rank_for_rating(1700).name == "Master"
    assert rank_game_cost(rank_for_rating(1000), GAME_KIND_DRAUGHTS) == 10
    assert rank_game_cost(rank_for_rating(1000), GAME_KIND_CHESS) == 15
    rank, cost = match_rank_and_cost(1080, 1120, GAME_KIND_DRAUGHTS)
    assert rank.name == "Gold"
    assert cost == 15


def test_matchmaking_callback_parser_keeps_all_choices() -> None:
    assert parse_matchmaking_callback("mm:join:chess:unrated:anon") == (
        "join",
        GAME_KIND_CHESS,
        False,
        True,
    )
    assert parse_matchmaking_callback("mm:cancel")[0] == "cancel"
    assert parse_global_timeout_callback("gmt:game-1:accept") == ("game-1", "accept", None)
    assert parse_global_timeout_callback("gmt:game-1:propose:300") == ("game-1", "propose", 300)
    assert parse_global_timeout_callback("gmt:game-1:cancel") == ("game-1", "cancel", None)
    assert parse_global_timeout_callback("gmt:game-1:propose:999") is None


def test_global_stats_use_rank_cost_not_local_value_formula() -> None:
    class Stats:
        rating = 1000
        games_played = 0
        wins = 0
        losses = 0
        draws = 0
        current_streak = 0
        best_streak = 0

    text = global_game_stats_text(GAME_KIND_CHESS, Stats(), 100, "@alice")

    assert "Rank: Silver" in text
    assert "Rated game cost: 15 kyzma-coins" in text
    assert "Game value" not in text


def test_rated_matchmaking_prefers_closest_eligible_rating(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        for user_id in (10, 20, 30):
            await database.upsert_user(UpsertUser(user_id, f"user{user_id}", f"User {user_id}", None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        old = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
        await database.add_matchmaking_entry(entry(10, 1000, old))
        await database.add_matchmaking_entry(entry(20, 1180, old))
        await database.add_matchmaking_entry(entry(30, 1050, old))

        pair = await database.claim_matchmaking_pair(10)

        assert pair is not None
        assert {pair[0].user_id, pair[1].user_id} == {10, 30}
        assert await database.get_matchmaking_entry(20) is not None
        database.close()

    asyncio.run(scenario())


def test_global_match_confirms_default_timeout_then_charges_and_starts(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        for user_id, username in ((10, "alice"), (20, "bob")):
            await database.upsert_user(UpsertUser(user_id, username, username.title(), None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        bot = FakeBot()

        await create_global_match(bot, database, entry(10, anonymous=True), entry(20))

        setup_edits = [edit for edit in bot.edits if "Timeout setup" in edit["text"]]
        assert len(setup_edits) == 2
        assert all("Default move timeout: 2 minutes" in edit["text"] for edit in setup_edits)
        assert all("Anonymous" in edit["text"] for edit in setup_edits)
        alice_wallet = await database.get_global_wallet(10)
        bob_wallet = await database.get_global_wallet(20)
        assert alice_wallet.kyzma_coin_balance == 100
        assert bob_wallet.kyzma_coin_balance == 100
        game = await database.get_active_global_game_for_user(10)
        assert game is not None
        state = DraughtsState.from_json(game.state)
        assert state.status is GameStatus.CONFIRMING
        assert state.global_game is True
        assert state.global_rank == "Silver"
        assert state.anonymous_user_ids == [10]
        assert state.move_timeout_seconds == default_move_timeout(GAME_KIND_DRAUGHTS) == 120
        assert len(await database.get_game_views(game.id)) == 2

        assert await accept_global_timeout(bot, database, game, state, 10) is False
        assert (await database.get_global_wallet(10)).kyzma_coin_balance == 100
        assert await accept_global_timeout(bot, database, game, state, 20) is True

        started_game = await database.get_game(game.id)
        started_state = DraughtsState.from_json(started_game.state)
        assert started_state.status is GameStatus.IN_PROGRESS
        assert started_state.turn_started_at is not None
        assert (await database.get_global_wallet(10)).kyzma_coin_balance == 90
        assert (await database.get_global_wallet(20)).kyzma_coin_balance == 90
        board_edits = [edit for edit in bot.edits if "Global match · Silver" in edit["text"]]
        assert len(board_edits) == 2
        assert all("Move timeout: 2 minutes" in edit["text"] for edit in board_edits)
        assert all("@alice" not in edit["text"] for edit in board_edits)
        database.close()

    asyncio.run(scenario())


def test_player_can_propose_chess_timeout_and_opponent_accepts(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        for user_id, username in ((10, "alice"), (20, "bob")):
            await database.upsert_user(UpsertUser(user_id, username, username.title(), None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        bot = FakeBot()
        await create_global_match(
            bot,
            database,
            entry(10, game_kind=GAME_KIND_CHESS),
            entry(20, game_kind=GAME_KIND_CHESS),
        )
        game = await database.get_active_global_game_for_user(10)
        state = ChessState.from_json(game.state)
        assert state.status is ChessStatus.CONFIRMING
        assert state.move_timeout_seconds == 180

        assert await request_global_timeout_change(bot, database, game, state, 10) is True
        assert await propose_global_timeout(bot, database, game, state, 10, 300) is True
        assert state.timeout_accepted_user_ids == [10]
        assert any("Proposed move timeout: 5 minutes" in edit["text"] for edit in bot.edits)
        assert await accept_global_timeout(bot, database, game, state, 10) is False
        assert await accept_global_timeout(bot, database, game, state, 20) is True

        started = ChessState.from_json((await database.get_game(game.id)).state)
        assert started.status is ChessStatus.IN_PROGRESS
        assert started.move_timeout_seconds == 300
        assert (await database.get_global_wallet(10)).kyzma_coin_balance == 85
        assert (await database.get_global_wallet(20)).kyzma_coin_balance == 85
        database.close()

    asyncio.run(scenario())


def test_timeout_setup_can_be_cancelled_without_charge(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        for user_id, username in ((10, "alice"), (20, "bob")):
            await database.upsert_user(UpsertUser(user_id, username, username.title(), None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        bot = FakeBot()
        await create_global_match(bot, database, entry(10), entry(20))
        game = await database.get_active_global_game_for_user(10)
        state = DraughtsState.from_json(game.state)

        await cancel_global_timeout(bot, database, game, state)

        assert (await database.get_game(game.id)).status == "finished"
        assert (await database.get_global_wallet(10)).kyzma_coin_balance == 100
        assert (await database.get_global_wallet(20)).kyzma_coin_balance == 100
        assert any("No coins were charged" in edit["text"] for edit in bot.edits)
        database.close()

    asyncio.run(scenario())


def test_stale_matchmaking_entries_expire_and_can_be_rejoined(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        now = datetime.now(UTC)
        for user_id in (10, 20):
            await database.upsert_user(UpsertUser(user_id, f"user{user_id}", f"User {user_id}", None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        await database.add_matchmaking_entry(entry(10, joined_at=(now - timedelta(minutes=31)).isoformat()))
        await database.add_matchmaking_entry(entry(20, joined_at=(now - timedelta(minutes=29)).isoformat()))
        bot = FakeBot()

        expired = await expire_stale_matchmaking_entries(bot, database, now)

        assert expired == [10]
        assert await database.get_matchmaking_entry(10) is None
        assert await database.get_matchmaking_entry(20) is not None
        assert "expired after 30 minutes" in bot.edits[0]["text"]
        assert bot.edits[0]["reply_markup"] is not None
        database.close()

    asyncio.run(scenario())


def test_stale_timeout_setup_expires_without_charging_players(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        for user_id, username in ((10, "alice"), (20, "bob")):
            await database.upsert_user(UpsertUser(user_id, username, username.title(), None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        bot = FakeBot()
        await create_global_match(bot, database, entry(10), entry(20))
        game = await database.get_active_global_game_for_user(10)
        now = datetime.now(UTC)
        database.conn.execute(
            "UPDATE games SET created_at = ? WHERE id = ?",
            ((now - timedelta(minutes=6)).isoformat(), game.id),
        )
        database.conn.commit()

        expired = await expire_stale_timeout_setups(bot, database, now)

        assert expired == [game.id]
        finished = await database.get_game(game.id)
        assert finished.status == "finished"
        assert finished.result_reason == "timeout setup expired"
        assert (await database.get_global_wallet(10)).kyzma_coin_balance == 100
        assert (await database.get_global_wallet(20)).kyzma_coin_balance == 100
        assert any("expired" in edit["text"] for edit in bot.edits)
        database.close()

    asyncio.run(scenario())


def test_global_rating_updates_separately_by_game(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.upsert_user(UpsertUser(20, "bob", "Bob", None, "en"))

        await database.update_global_stats_after_game(GameOutcome(0, GAME_KIND_CHESS, 10, 20, 10))

        alice_chess = await database.get_global_user_stats(10, GAME_KIND_CHESS)
        alice_draughts = await database.ensure_global_user_stats(10, GAME_KIND_DRAUGHTS)
        assert alice_chess.rating == 1016
        assert alice_chess.wins == 1
        assert alice_draughts.rating == 1000
        assert alice_draughts.games_played == 0
        database.close()

    asyncio.run(scenario())


def test_global_game_finish_updates_rating_and_prize_once(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        for user_id, username in ((10, "alice"), (20, "bob")):
            await database.upsert_user(UpsertUser(user_id, username, username.title(), None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        await create_global_match(FakeBot(), database, entry(10), entry(20))
        game = await database.get_active_global_game_for_user(10)
        state = DraughtsState.from_json(game.state)
        await accept_global_timeout(FakeBot(), database, game, state, 10)
        await accept_global_timeout(FakeBot(), database, game, state, 20)
        game = await database.get_game(game.id)
        state = DraughtsState.from_json(game.state)
        state.status = GameStatus.FINISHED
        state.winner = PieceColor.WHITE
        state.result_reason = "test win"
        winner_id = state.white_user_id
        prize = state.kyzma_prize

        await finish_rated_game(database, game, state)
        await finish_rated_game(database, game, state)

        stats = await database.get_global_user_stats(winner_id, GAME_KIND_DRAUGHTS)
        wallet = await database.get_global_wallet(winner_id)
        assert stats.games_played == 1
        assert stats.wins == 1
        assert wallet.kyzma_coin_balance == 90 + prize
        database.close()

    asyncio.run(scenario())


def test_expired_move_timeout_awards_game_to_opponent(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        for user_id, username in ((10, "alice"), (20, "bob")):
            await database.upsert_user(UpsertUser(user_id, username, username.title(), None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        bot = FakeBot()
        await create_global_match(bot, database, entry(10), entry(20))
        game = await database.get_active_global_game_for_user(10)
        state = DraughtsState.from_json(game.state)
        await accept_global_timeout(bot, database, game, state, 10)
        await accept_global_timeout(bot, database, game, state, 20)
        game = await database.get_game(game.id)
        state = DraughtsState.from_json(game.state)
        losing_user_id = state.current_user_id()
        winner_user_id = state.black_user_id if losing_user_id == state.white_user_id else state.white_user_id
        prize = state.kyzma_prize
        now = datetime.now(UTC)
        state.turn_started_at = (now - timedelta(seconds=121)).isoformat()
        await database.update_game_state(global_state_update(game, state, state.current_user_id()))

        expired = await expire_overdue_global_games(bot, database, now)

        finished_game = await database.get_game(game.id)
        finished_state = DraughtsState.from_json(finished_game.state)
        winner_stats = await database.get_global_user_stats(winner_user_id, GAME_KIND_DRAUGHTS)
        winner_wallet = await database.get_global_wallet(winner_user_id)
        assert expired == [game.id]
        assert finished_game.status == "finished"
        assert finished_state.result_reason == "move timeout"
        assert finished_state.winner_user_id() == winner_user_id
        assert winner_stats.wins == 1
        assert winner_wallet.kyzma_coin_balance == 90 + prize
        database.close()

    asyncio.run(scenario())


def test_completed_global_move_resets_turn_timer(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        for user_id, username in ((10, "alice"), (20, "bob")):
            await database.upsert_user(UpsertUser(user_id, username, username.title(), None, "en"))
            await database.upsert_chat(UpsertChat(user_id, None, "private"))
        bot = FakeBot()
        await create_global_match(bot, database, entry(10), entry(20))
        game = await database.get_active_global_game_for_user(10)
        state = DraughtsState.from_json(game.state)
        await accept_global_timeout(bot, database, game, state, 10)
        await accept_global_timeout(bot, database, game, state, 20)
        game = await database.get_game(game.id)
        state = DraughtsState.from_json(game.state)
        old_started_at = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
        state.turn_started_at = old_started_at
        user_id = state.current_user_id()
        move = state.legal_moves()[0]

        await play_move_and_update(
            SimpleNamespace(bot=bot),
            database,
            None,
            MessageTarget(chat_id=user_id, message_id=user_id * 10),
            game,
            state,
            move,
            user_id,
        )

        restored = DraughtsState.from_json((await database.get_game(game.id)).state)
        assert restored.turn_started_at != old_started_at
        assert restored.current_user_id() != user_id
        database.close()

    asyncio.run(scenario())
