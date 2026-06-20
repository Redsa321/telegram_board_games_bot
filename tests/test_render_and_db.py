import asyncio

from telegram import User

from telegram_board_games_bot.commands import render_stats_text, render_wallet_text
from telegram_board_games_bot.db import Database, GameOutcome, UpsertChat, UpsertUser, elo_rating
from telegram_board_games_bot.games.draughts import Coord, DraughtsMove, DraughtsState, GameStatus, PieceColor
from telegram_board_games_bot.i18n import Lang
from telegram_board_games_bot.render.text_board import (
    move_label,
    render_draughts_confirmation_keyboard,
    render_draughts_confirmation_message,
    render_draughts_invite_keyboard,
    render_draughts_invite_message,
    render_draughts_keyboard,
    render_draughts_message,
)


def test_renders_initial_message_and_keyboard() -> None:
    state = DraughtsState.new(10, 20)
    state.kyzma_prize_base = 10
    state.kyzma_prize_multiplier = 3
    state.kyzma_prize = 30
    message = render_draughts_message(state, "@alice", "@bob", True, Lang.EN)
    keyboard = render_draughts_keyboard("game", state, Lang.EN)

    assert "Draughts · Rated" in message
    assert "@alice — ⚫ Black" in message
    assert "@bob — ⚪ White" in message
    assert "Move: 1" in message
    assert "Prize: 10 kyzma-coins ×3 = 30" in message
    assert "Turn: @bob — ⚪" in message
    assert len(keyboard.inline_keyboard) == 9
    assert keyboard.inline_keyboard[2][1].text == "⚫"
    assert keyboard.inline_keyboard[-1][0].text == "Resign"


def test_renders_invite_with_challenger_value_and_modes() -> None:
    message = render_draughts_invite_message("@alice", Lang.EN, 72)
    keyboard = render_draughts_invite_keyboard(10, Lang.EN)

    assert "Draughts invite" in message
    assert "@alice — ⚫ Black" in message
    assert "Game value: 72" in message
    assert keyboard.inline_keyboard[0][0].text == "Join rated"
    assert keyboard.inline_keyboard[0][0].callback_data == "dg:10:join"
    assert keyboard.inline_keyboard[1][0].text == "Join unrated"
    assert keyboard.inline_keyboard[1][0].callback_data == "dg:10:joinu"


def test_renders_rated_confirmation() -> None:
    state = DraughtsState.new(10, 20)
    state.status = GameStatus.CONFIRMING
    state.kyzma_prize_base = 10
    state.kyzma_prize_multiplier = 3
    state.kyzma_prize = 30
    state.accepted_user_ids = [10]

    message = render_draughts_confirmation_message(state, "@alice", "@bob", Lang.EN)
    keyboard = render_draughts_confirmation_keyboard("game", Lang.EN)

    assert "Confirm rated game" in message
    assert "Game cost: 10 kyzma-coins" in message
    assert "Both players are charged this cost when the game starts." in message
    assert "Prize: 10 kyzma-coins ×3 = 30" in message
    assert "Accepted: 1/2" in message
    assert keyboard.inline_keyboard[0][0].text == "Accept"
    assert keyboard.inline_keyboard[0][0].callback_data == "dg:game:accept"


def test_keyboard_keeps_square_symbols_while_encoding_selected_piece() -> None:
    state = DraughtsState.new(10, 20)
    state.selected = Coord(5, 0)

    keyboard = render_draughts_keyboard("game", state, Lang.EN)

    assert keyboard.inline_keyboard[5][0].text == "⚪"
    assert keyboard.inline_keyboard[4][1].text == "·"
    assert keyboard.inline_keyboard[4][1].callback_data == "dg:game:sq:41:50"


def test_renders_finished_message_and_buttons() -> None:
    state = DraughtsState.new(10, 20)
    state.status = GameStatus.FINISHED
    state.winner = PieceColor.BLACK
    state.result_reason = "opponent has no legal moves"

    message = render_draughts_message(state, "@alice", "@bob", True, Lang.EN)
    keyboard = render_draughts_keyboard("game", state, Lang.EN)

    assert "🏁 Game over" in message
    assert "Winner: @alice ⚫" in message
    assert "Reason: White has no legal moves" in message
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["Play again", "Stats"]


def test_move_label_uses_capture_notation() -> None:
    move = DraughtsMove(Coord(5, 0), [Coord(2, 3)])
    assert move_label(move, True) == "A3xD6"
    assert move_label(move, False) == "A3-D6"


def test_stats_text_shows_username_without_user_id() -> None:
    user = User(id=123, first_name="Alice", is_bot=False, username="alice")

    text = render_stats_text(Lang.EN, None, user)

    assert text.startswith("Player: @alice\n")
    assert "123" not in text
    assert "Games: 0" in text
    assert "Rating: 1000" in text
    assert "kyzma-coins: 100" in text
    assert "Game value: 50" in text


def test_wallet_text_shows_balance_value_and_claim_hint() -> None:
    user = User(id=123, first_name="Alice", is_bot=False, username="alice")

    text = render_wallet_text(Lang.EN, None, user)

    assert text.startswith("Player: @alice\n")
    assert "123" not in text
    assert "Wallet" in text
    assert "kyzma-coins: 100" in text
    assert "Game value: 50" in text
    assert "Daily bonus: /claim" in text


def test_database_stats_update(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(100, "group", "group"))
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.upsert_user(UpsertUser(20, "bob", "Bob", None, "en"))

        await database.update_stats_after_game(GameOutcome(100, "draughts", 10, 20, 10))
        alice = await database.get_user_stats(100, 10, "draughts")
        bob = await database.get_user_stats(100, 20, "draughts")

        assert alice.wins == 1
        assert alice.rating == 1016
        assert alice.kyzma_coin_balance == 100
        assert bob.losses == 1
        assert bob.rating == 984
        assert bob.kyzma_coin_balance == 100
        assert elo_rating(1000, 1000, 1.0) == 1016
        database.close()

    asyncio.run(scenario())
