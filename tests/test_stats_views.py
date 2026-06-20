import asyncio

from telegram_board_games_bot.db import Database, GameOutcome, UpsertUser
from telegram_board_games_bot.stats_views import parse_selector_data, selector_keyboard


def test_stats_selector_callback_round_trips() -> None:
    assert parse_selector_data("st:stats:global:chess") == ("stats", "global", "chess")
    assert parse_selector_data("st:top:local:draughts") == ("top", "local", "draughts")
    assert parse_selector_data("st:stats:planet:chess") is None
    keyboard = selector_keyboard("stats", "global", "chess")
    assert keyboard.inline_keyboard[0][1].text.startswith("✓")
    assert keyboard.inline_keyboard[1][1].text.startswith("✓")


def test_global_leaderboard_is_separate_by_game_kind(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.upsert_user(UpsertUser(20, "bob", "Bob", None, "en"))
        await database.update_global_stats_after_game(GameOutcome(0, "chess", 10, 20, 10))

        chess = await database.get_global_leaderboard("chess", 10)
        draughts = await database.get_global_leaderboard("draughts", 10)

        assert [entry.username for entry in chess] == ["alice", "bob"]
        assert chess[0].rating > chess[1].rating
        assert draughts == []
        database.close()

    asyncio.run(scenario())
