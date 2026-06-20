from telegram_board_games_bot import i18n
from telegram_board_games_bot.i18n import Lang


def test_play_robot_is_advertised_in_command_menu_and_help_text() -> None:
    command_names = [name for name, _ in i18n.bot_command_descriptions(Lang.EN)]

    assert "play_robot" in command_names
    assert "/play_robot" in i18n.command_list_text(Lang.EN)
    assert "play_chess" in command_names
    assert "/play_chess" in i18n.command_list_text(Lang.EN)
    assert "play_chess_robot" in command_names
    assert "/play_chess_robot" in i18n.command_list_text(Lang.EN)
    assert "play_random" in command_names
    assert "/play_random" in i18n.command_list_text(Lang.EN)
    assert "global_stats" in command_names
    assert "wallet" in command_names
    assert "/wallet" in i18n.command_list_text(Lang.EN)
    assert "claim" in command_names
    assert "/claim" in i18n.command_list_text(Lang.EN)


def test_start_message_explains_robot_games_and_coins() -> None:
    text = i18n.welcome(Lang.EN)

    assert "Draughts basics:" in text
    assert "Chess basics:" in text
    assert "/play_robot starts a free game against the robot." in text
    assert "/play_chess_robot starts a free chess game against the robot." in text
    assert "/play_random" in text
    assert "/global_stats" in text
    assert "divided by 5" in text
    assert "2x" in text
    assert "Win free robot games to earn coins." in text
    assert "/wallet" in text
    assert "/claim" in text


def test_kyzma_coin_name_translations() -> None:
    assert i18n.kyzma_coin_name(Lang.EN) == "kyzma-coins"
    assert i18n.kyzma_coin_name(Lang.UK) == "кузьмакоін"
    assert i18n.kyzma_coin_name(Lang.RU) == "кузьмакоин"
    assert i18n.kyzma_coin_name(Lang.PL) == "kyzma-coins"
