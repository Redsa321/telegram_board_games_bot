import asyncio

from telegram.error import NetworkError, RetryAfter

from telegram_board_games_bot.telegram_retry import edit_message_text_with_retry


def test_board_edit_retries_temporary_network_errors(monkeypatch) -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls = 0

        async def edit_message_text(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise NetworkError("temporary failure")

    async def no_sleep(delay):
        return None

    async def scenario() -> None:
        bot = Bot()
        monkeypatch.setattr("telegram_board_games_bot.telegram_retry.asyncio.sleep", no_sleep)

        assert await edit_message_text_with_retry(bot, text="board", chat_id=1, message_id=2)
        assert bot.calls == 3

    asyncio.run(scenario())


def test_board_edit_waits_for_telegram_flood_control(monkeypatch) -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls = 0

        async def edit_message_text(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RetryAfter(9)

    delays = []

    async def record_sleep(delay):
        delays.append(delay)

    async def scenario() -> None:
        bot = Bot()
        monkeypatch.setattr("telegram_board_games_bot.telegram_retry.asyncio.sleep", record_sleep)

        assert await edit_message_text_with_retry(bot, text="board", chat_id=1, message_id=2)
        assert bot.calls == 2
        assert delays == [9.25]

    asyncio.run(scenario())
