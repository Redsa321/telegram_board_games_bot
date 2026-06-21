import asyncio
from types import SimpleNamespace

from telegram import User
from telegram.constants import ChatType

from telegram_board_games_bot.commands import admin_message_payload, handle_admin_message
from telegram_board_games_bot.config import Config
from telegram_board_games_bot.db import Database, UpsertChat


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


def test_admin_message_payload_preserves_multiline_text() -> None:
    assert admin_message_payload("/admin_message First line\nSecond line") == "First line\nSecond line"
    assert admin_message_payload("/admin_message") == ""


def test_active_group_registry_excludes_private_and_removed_chats(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(1, "private", ChatType.PRIVATE))
        await database.upsert_chat(UpsertChat(-10, "group", ChatType.GROUP))
        await database.upsert_chat(UpsertChat(-20, "supergroup", ChatType.SUPERGROUP))
        await database.set_chat_active(-20, False)

        groups = await database.get_active_group_chats()

        assert [group.telegram_chat_id for group in groups] == [-10]
        database.close()

    asyncio.run(scenario())


def test_admin_broadcast_sends_to_every_known_active_group(tmp_path) -> None:
    async def scenario() -> None:
        database = Database.connect(str(tmp_path / "bot.db"))
        await database.run_migrations()
        await database.upsert_chat(UpsertChat(-10, "one", ChatType.GROUP))
        await database.upsert_chat(UpsertChat(-20, "two", ChatType.SUPERGROUP))
        bot = FakeBot()
        message = FakeMessage("/admin_message Maintenance in ten minutes")
        context = SimpleNamespace(
            bot=bot,
            application=SimpleNamespace(bot_data={
                "database": database,
                "config": Config("token", admin_user_id=783115680),
            }),
        )
        update = SimpleNamespace(
            effective_message=message,
            effective_user=User(783115680, "Admin", False, username="onopriienkoos"),
            effective_chat=SimpleNamespace(type=ChatType.PRIVATE),
        )

        await handle_admin_message(update, context)

        assert [sent["chat_id"] for sent in bot.sent] == [-20, -10]
        assert all("Maintenance in ten minutes" in sent["text"] for sent in bot.sent)
        assert message.replies == ["Broadcast complete. Sent: 2. Failed: 0. Known active groups: 2."]
        database.close()

    asyncio.run(scenario())
