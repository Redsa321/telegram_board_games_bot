import asyncio

from fastapi.testclient import TestClient

from telegram_board_games_bot.admin_web import create_admin_app
from telegram_board_games_bot.config import Config
from telegram_board_games_bot.db import Database, FinishGame, NewGame, UpsertChat, UpsertUser
from telegram_board_games_bot.games.draughts import DraughtsState


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


def prepared_database(tmp_path) -> str:
    async def prepare(database: Database) -> None:
        await database.upsert_chat(UpsertChat(-100, "Chess Club", "supergroup"))
        await database.upsert_user(UpsertUser(10, "alice", "Alice", None, "en"))
        await database.upsert_user(UpsertUser(20, "bob", "Bob", None, "uk"))
        wallet = await database.ensure_global_wallet(10)
        database.conn.execute(
            "UPDATE global_wallets SET kyzma_coin_balance = 145 WHERE user_id = ?",
            (wallet.user_id,),
        )
        state = DraughtsState.new(10, 20)
        game = await database.create_game(NewGame(
            chat_id=-100,
            message_id=1,
            inline_message_id=None,
            game_kind="draughts",
            status="in_progress",
            rated=True,
            state=state,
            current_turn_user_id=state.current_user_id(),
            black_user_id=10,
            white_user_id=20,
        ))
        await database.finish_game(FinishGame(game.id, 10, "test win"))
        await database.award_kyzma_coins_once(
            game_id="daily:10:2026-06-22",
            chat_id=-100,
            user_id=10,
            game_kind="draughts",
            amount=10,
            multiplier=None,
            reason="daily_claim",
        )

    database = Database.connect(str(tmp_path / "bot.db"))
    database._run_migrations()
    asyncio.run(prepare(database))
    path = str(database.path)
    database.close()
    return path


def test_admin_api_requires_token_and_exposes_groups_users_and_events(tmp_path) -> None:
    database_path = prepared_database(tmp_path)
    config = Config("bot-token", database_url=database_path, admin_web_token="secret")
    app = create_admin_app(config, telegram_bot=FakeBot())

    with TestClient(app) as client:
        assert client.get("/api/overview").status_code == 401
        headers = {"Authorization": "Bearer secret"}
        overview = client.get("/api/overview", headers=headers).json()
        groups = client.get("/api/groups?q=chess", headers=headers).json()
        users = client.get("/api/users?q=10", headers=headers).json()
        detail = client.get("/api/users/10", headers=headers).json()
        events = client.get("/api/groups/-100/events", headers=headers).json()

    assert overview["users"] == 2
    assert groups[0]["chat_id"] == -100
    assert users[0]["display_name"] == "@alice"
    assert detail["balance"] == 155
    assert {event["type"] for event in events} == {"game_finished", "coin_event"}


def test_admin_web_message_sends_and_is_added_to_group_activity(tmp_path) -> None:
    database_path = prepared_database(tmp_path)
    bot = FakeBot()
    config = Config("bot-token", database_url=database_path, admin_user_id=10, admin_web_token="secret")
    app = create_admin_app(config, telegram_bot=bot)
    headers = {"Authorization": "Bearer secret"}

    with TestClient(app) as client:
        unknown_response = client.post(
            "/api/messages",
            headers=headers,
            json={"text": "No destination", "chat_ids": [-999], "all_active_groups": False},
        )
        response = client.post(
            "/api/messages",
            headers=headers,
            json={"text": "Server maintenance", "chat_ids": [-100], "all_active_groups": False},
        )
        events = client.get("/api/groups/-100/events", headers=headers).json()

    assert unknown_response.status_code == 422
    assert response.status_code == 200
    assert response.json() == {"sent": [-100], "failed": []}
    assert bot.sent == [{"chat_id": -100, "text": "Server maintenance"}]
    assert any(event["type"] == "admin_message" for event in events)
