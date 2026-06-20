from __future__ import annotations

from enum import StrEnum
from typing import Any

from .economy import STARTER_KYZMA_COINS, kyzma_value_from_rating
from .games.draughts import PieceColor


class Lang(StrEnum):
    EN = "en"
    UK = "uk"
    RU = "ru"
    PL = "pl"

    @classmethod
    def from_code(cls, code: str | None) -> "Lang":
        primary = (code or "").replace("_", "-").split("-")[0].lower()
        return {
            "uk": cls.UK,
            "ru": cls.RU,
            "pl": cls.PL,
        }.get(primary, cls.EN)

    @property
    def telegram_code(self) -> str | None:
        return None if self is Lang.EN else self.value


ALL_LANGS = [Lang.EN, Lang.UK, Lang.RU, Lang.PL]


def tr(lang: Lang, *, en: str, uk: str, ru: str, pl: str) -> str:
    return {Lang.EN: en, Lang.UK: uk, Lang.RU: ru, Lang.PL: pl}[lang]


def user_lang(user: Any | None) -> Lang:
    return Lang.from_code(getattr(user, "language_code", None))


def db_user_lang(user: Any | None) -> Lang:
    return Lang.from_code(getattr(user, "language_code", None))


COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "command_start"),
    ("help", "command_help"),
    ("play_draughts", "command_play_draughts"),
    ("play_chess", "command_play_chess"),
    ("play_robot", "command_play_robot"),
    ("play_chess_robot", "command_play_chess_robot"),
    ("play_random", "command_play_random"),
    ("cancel_global", "command_cancel_global"),
    ("resume_global", "command_resume_global"),
    ("global_stats", "command_global_stats"),
    ("stats", "command_stats"),
    ("wallet", "command_wallet"),
    ("claim", "command_claim"),
    ("top", "command_top"),
    ("global_top", "command_global_top"),
    ("feedback", "command_feedback"),
    ("privacy", "command_privacy"),
    ("about", "command_about"),
    ("resign", "command_resign"),
)


def welcome(lang: Lang) -> str:
    return tr(lang,
        en=(
            "Hi! This is a public beta of board games played directly inside Telegram messages.\n\n"
            "Draughts basics:\n"
            "• White moves first.\n"
            "• Captures are mandatory, including continued captures.\n"
            "• Men move forward and can capture forward or backward.\n"
            "• Kings move and capture across open diagonals.\n"
            "• You lose if you have no pieces or no legal moves.\n\n"
            "Chess basics:\n"
            "• Standard chess rules. White moves first.\n"
            "• Tap one of your pieces, then tap its destination.\n"
            "• Checkmate wins; stalemate and draw rules are handled automatically.\n\n"
            "Play with people:\n"
            "• /play_draughts posts an invite.\n"
            "• /play_chess posts a chess invite.\n"
            "• Rated games cost kyzma-coins, both players confirm the cost, and the result changes rating.\n"
            "• Rated game cost is the average of both player values divided by 5. The winner prize starts at 2x that cost.\n"
            "• Chess costs 1.5x more and can win 2x more coins because games last longer.\n"
            "• Unrated games are free and do not affect rating.\n\n"
            "Robot games:\n"
            "• /play_robot starts a free game against the robot.\n"
            "• /play_chess_robot starts a free chess game against the robot.\n"
            "• Choose Easy, Normal, or Hard.\n"
            "• Robot games do not change rating.\n"
            "• Win free robot games to earn coins.\n\n"
            "Global games:\n"
            "• Use /play_random in private chat for an English-language random match.\n"
            "• Choose rated or unrated, and choose whether your name is visible.\n"
            "• Both players confirm the move timeout: 2 minutes for draughts or 3 for chess by default.\n"
            "• Use /global_stats for global chess and draughts ranks.\n\n"
            "Use /wallet for your balance, /claim for a daily coin bonus, /stats for full stats, and /top for the leaderboard."
        ),
        uk=(
            "Привіт! Це публічна бета-версія настільних ігор прямо в повідомленнях Telegram.\n\n"
            "Основи шашок:\n"
            "• Білі ходять першими.\n"
            "• Взяття обов'язкове, включно з продовженням серії взяттів.\n"
            "• Прості шашки ходять вперед і можуть бити вперед або назад.\n"
            "• Дамки ходять і б'ють по відкритих діагоналях.\n"
            "• Ви програєте, якщо немає фігур або допустимих ходів.\n\n"
            "Основи шахів:\n"
            "• Стандартні правила шахів. Білі ходять першими.\n"
            "• Натисніть свою фігуру, потім клітинку призначення.\n"
            "• Мат перемагає; пат і правила нічиєї обробляються автоматично.\n\n"
            "Гра з людьми:\n"
            "• /play_draughts надсилає запрошення.\n"
            "• /play_chess надсилає запрошення на шахи.\n"
            "• Рейтингові ігри коштують кузьмакоіни, обидва гравці підтверджують вартість, а результат змінює рейтинг.\n"
            "• Вартість рейтингової гри — це середнє значення вартості обох гравців, поділене на 5. Приз переможця починається з 2x цієї вартості.\n"
            "• Шахи коштують у 1.5x більше й можуть дати у 2x більше монет, бо партії довші.\n"
            "• Нерейтингові ігри безкоштовні й не впливають на рейтинг.\n\n"
            "Ігри з роботом:\n"
            "• /play_robot починає безкоштовну гру проти робота.\n"
            "• /play_chess_robot починає безкоштовну гру в шахи проти робота.\n"
            "• Оберіть Easy, Normal або Hard.\n"
            "• Ігри з роботом не змінюють рейтинг.\n"
            "• Перемагайте в безкоштовних іграх з роботом, щоб заробляти монети.\n\n"
            "Глобальні ігри:\n"
            "• Використовуйте /play_random у приватному чаті для випадкової гри англійською.\n"
            "• Оберіть рейтингову або нерейтингову гру та видимість свого імені.\n"
            "• Обидва гравці підтверджують час на хід: типово 2 хвилини для шашок і 3 для шахів.\n"
            "• Використовуйте /global_stats для глобальних рангів у шахах і шашках.\n\n"
            "Використовуйте /wallet для балансу, /claim для щоденного бонусу монет, /stats для повної статистики, а /top для таблиці лідерів."
        ),
        ru=(
            "Привет! Это публичная бета-версия настольных игр прямо в сообщениях Telegram.\n\n"
            "Основы шашек:\n"
            "• Белые ходят первыми.\n"
            "• Взятие обязательно, включая продолжение серии взятий.\n"
            "• Простые шашки ходят вперёд и могут бить вперёд или назад.\n"
            "• Дамки ходят и бьют по открытым диагоналям.\n"
            "• Вы проигрываете, если нет фигур или допустимых ходов.\n\n"
            "Основы шахмат:\n"
            "• Стандартные правила шахмат. Белые ходят первыми.\n"
            "• Нажмите свою фигуру, затем клетку назначения.\n"
            "• Мат побеждает; пат и правила ничьей обрабатываются автоматически.\n\n"
            "Игра с людьми:\n"
            "• /play_draughts отправляет приглашение.\n"
            "• /play_chess отправляет приглашение на шахматы.\n"
            "• Рейтинговые игры стоят кузьмакоины, оба игрока подтверждают стоимость, а результат меняет рейтинг.\n"
            "• Стоимость рейтинговой игры — это среднее значение стоимости обоих игроков, разделённое на 5. Приз победителя начинается с 2x этой стоимости.\n"
            "• Шахматы стоят в 1.5x больше и могут дать в 2x больше монет, потому что партии дольше.\n"
            "• Нерейтинговые игры бесплатные и не влияют на рейтинг.\n\n"
            "Игры с роботом:\n"
            "• /play_robot начинает бесплатную игру против робота.\n"
            "• /play_chess_robot начинает бесплатную игру в шахматы против робота.\n"
            "• Выберите Easy, Normal или Hard.\n"
            "• Игры с роботом не меняют рейтинг.\n"
            "• Побеждайте в бесплатных играх с роботом, чтобы зарабатывать монеты.\n\n"
            "Глобальные игры:\n"
            "• Используйте /play_random в личном чате для случайной игры на английском.\n"
            "• Выберите рейтинговую или нерейтинговую игру и видимость своего имени.\n"
            "• Оба игрока подтверждают время на ход: по умолчанию 2 минуты для шашек и 3 для шахмат.\n"
            "• Используйте /global_stats для глобальных рангов в шахматах и шашках.\n\n"
            "Используйте /wallet для баланса, /claim для ежедневного бонуса монет, /stats для полной статистики, а /top для таблицы лидеров."
        ),
        pl=(
            "Cześć! To publiczna beta gier planszowych bezpośrednio w wiadomościach Telegram.\n\n"
            "Podstawy warcabów:\n"
            "• Białe zaczynają.\n"
            "• Bicie jest obowiązkowe, także dalsze bicia w serii.\n"
            "• Pionki ruszają się do przodu i mogą bić do przodu lub do tyłu.\n"
            "• Damki poruszają się i biją po otwartych przekątnych.\n"
            "• Przegrywasz, jeśli nie masz pionków albo legalnych ruchów.\n\n"
            "Podstawy szachów:\n"
            "• Standardowe zasady szachów. Białe zaczynają.\n"
            "• Naciśnij własną figurę, a potem pole docelowe.\n"
            "• Mat wygrywa; pat i zasady remisu są obsługiwane automatycznie.\n\n"
            "Gra z ludźmi:\n"
            "• /play_draughts wysyła zaproszenie.\n"
            "• /play_chess wysyła zaproszenie do szachów.\n"
            "• Gry rankingowe kosztują kyzma-coins, obaj gracze potwierdzają koszt, a wynik zmienia ranking.\n"
            "• Koszt gry rankingowej to średnia wartości obu graczy podzielona przez 5. Nagroda zwycięzcy zaczyna się od 2x tego kosztu.\n"
            "• Szachy kosztują 1.5x więcej i mogą dać 2x więcej monet, bo partie trwają dłużej.\n"
            "• Gry towarzyskie są darmowe i nie wpływają na ranking.\n\n"
            "Gry z robotem:\n"
            "• /play_robot zaczyna darmową grę przeciw robotowi.\n"
            "• /play_chess_robot zaczyna darmową grę w szachy przeciw robotowi.\n"
            "• Wybierz Easy, Normal albo Hard.\n"
            "• Gry z robotem nie zmieniają rankingu.\n"
            "• Wygrywaj darmowe gry z robotem, aby zarabiać monety.\n\n"
            "Gry globalne:\n"
            "• Użyj /play_random w prywatnym czacie, aby znaleźć losową grę po angielsku.\n"
            "• Wybierz grę rankingową lub towarzyską oraz widoczność nazwy.\n"
            "• Obaj gracze potwierdzają czas ruchu: domyślnie 2 minuty w warcabach i 3 w szachach.\n"
            "• Użyj /global_stats, aby zobaczyć globalne rangi szachów i warcabów.\n\n"
            "Użyj /wallet po saldo, /claim po dzienny bonus monet, /stats po pełne statystyki, a /top po tabelę liderów."
        ))


def help_rules(lang: Lang) -> str:
    return tr(lang,
        en="Rules summary:\n• Draughts: English draughts on an 8x8 board; captures are mandatory, including continued captures.\n• Draughts: men move forward and capture forward or backward; kings move and capture across open diagonals.\n• Chess: standard chess rules; White moves first, promotion is selected when needed, and draw rules are handled automatically.",
        uk="Короткі правила:\n• Шашки: класичні шашки на дошці 8x8; взяття обов'язкове, включно з продовженням серії.\n• Шашки: прості ходять вперед і б'ють вперед або назад; дамки ходять і б'ють по відкритих діагоналях.\n• Шахи: стандартні правила шахів; білі ходять першими, перетворення обирається за потреби, нічиї обробляються автоматично.",
        ru="Краткие правила:\n• Шашки: классические шашки на доске 8x8; взятие обязательно, включая продолжение серии.\n• Шашки: простые ходят вперёд и бьют вперёд или назад; дамки ходят и бьют по открытым диагоналям.\n• Шахматы: стандартные правила; белые ходят первыми, превращение выбирается при необходимости, ничьи обрабатываются автоматически.",
        pl="Skrót zasad:\n• Warcaby: warcaby angielskie na planszy 8x8; bicie jest obowiązkowe, także dalsze bicia w serii.\n• Warcaby: pionki idą do przodu i biją do przodu lub do tyłu; damki poruszają się i biją po otwartych przekątnych.\n• Szachy: standardowe zasady; białe zaczynają, promocję wybierasz w razie potrzeby, a remisy są obsługiwane automatycznie.")


def help_footer(lang: Lang) -> str:
    return tr(lang,
        en="Start a game with /play_draughts or /play_chess, then another player can tap Join.",
        uk="Почніть гру через /play_draughts або /play_chess, після цього інший гравець може натиснути «Приєднатися».",
        ru="Начните игру через /play_draughts или /play_chess, после этого другой игрок может нажать «Присоединиться».",
        pl="Zacznij grę za pomocą /play_draughts albo /play_chess, a inny gracz będzie mógł nacisnąć „Dołącz”.")


def about_text(lang: Lang, version: str) -> str:
    return tr(
        lang,
        en=f"Telegram Board Games Bot\nVersion {version}\n\nPublic beta with draughts, chess, robot games, global matchmaking, ratings, and kyzma-coins. Use /feedback to report a problem.",
        uk=f"Telegram Board Games Bot\nВерсія {version}\n\nПублічна бета-версія з шашками, шахами, роботами, глобальним пошуком, рейтингами та кузьмакоінами. Повідомити про проблему: /feedback.",
        ru=f"Telegram Board Games Bot\nВерсия {version}\n\nПубличная бета-версия с шашками, шахматами, роботами, глобальным поиском, рейтингами и кузьмакоинами. Сообщить о проблеме: /feedback.",
        pl=f"Telegram Board Games Bot\nWersja {version}\n\nPubliczna beta z warcabami, szachami, robotami, globalnym dobieraniem graczy, rankingami i kyzma-coins. Zgłoś problem przez /feedback.",
    )


def privacy_text(lang: Lang) -> str:
    return tr(
        lang,
        en=("Privacy\n\nThe bot stores Telegram user and chat IDs, usernames and names, game history, ratings, and coin transactions so games and accounts work across restarts. Anonymous global mode hides your name from your opponent; it does not remove your ID from bot storage. Feedback includes your user ID and may include a replied-to game ID. Contact the bot administrator through /feedback to request account-data deletion."),
        uk=("Конфіденційність\n\nБот зберігає ID користувачів і чатів Telegram, імена, історію ігор, рейтинги та операції з монетами, щоб ігри й акаунти працювали після перезапуску. Анонімний глобальний режим приховує ім'я від суперника, але не видаляє ID зі сховища бота. Відгук містить ваш ID та може містити ID гри. Запит на видалення даних надішліть адміністратору через /feedback."),
        ru=("Конфиденциальность\n\nБот хранит ID пользователей и чатов Telegram, имена, историю игр, рейтинги и операции с монетами, чтобы игры и аккаунты работали после перезапуска. Анонимный глобальный режим скрывает имя от соперника, но не удаляет ID из хранилища бота. Отзыв содержит ваш ID и может содержать ID игры. Запрос на удаление данных отправьте администратору через /feedback."),
        pl=("Prywatność\n\nBot przechowuje identyfikatory użytkowników i czatów Telegram, nazwy, historię gier, rankingi i transakcje monet, aby gry i konta działały po restarcie. Tryb anonimowy ukrywa nazwę przed przeciwnikiem, ale nie usuwa ID z pamięci bota. Opinia zawiera ID użytkownika i może zawierać ID gry. Prośbę o usunięcie danych wyślij administratorowi przez /feedback."),
    )


def feedback_usage(lang: Lang) -> str:
    return tr(lang, en="Usage: /feedback describe the problem. Reply to a game message to attach its game ID.", uk="Використання: /feedback опишіть проблему. Дайте відповідь на повідомлення гри, щоб додати її ID.", ru="Использование: /feedback опишите проблему. Ответьте на сообщение игры, чтобы добавить её ID.", pl="Użycie: /feedback opisz problem. Odpowiedz na wiadomość gry, aby dołączyć jej ID.")


def feedback_unavailable(lang: Lang) -> str:
    return tr(lang, en="Feedback is not configured yet.", uk="Зворотний зв'язок ще не налаштовано.", ru="Обратная связь ещё не настроена.", pl="Opinie nie są jeszcze skonfigurowane.")


def feedback_sent(lang: Lang, game_id: str | None) -> str:
    attached = f" Game ID: {game_id}." if game_id else ""
    return tr(lang, en=f"Feedback sent. Thank you.{attached}", uk=f"Відгук надіслано. Дякуємо.{attached}", ru=f"Отзыв отправлен. Спасибо.{attached}", pl=f"Opinia została wysłana. Dziękujemy.{attached}")


def command_start(lang: Lang) -> str:
    return tr(lang, en="Start the bot", uk="Запустити бота", ru="Запустить бота", pl="Uruchom bota")


def command_help(lang: Lang) -> str:
    return tr(lang, en="Show commands and game rules", uk="Показати команди та правила ігор", ru="Показать команды и правила игр", pl="Pokaż komendy i zasady gier")


def command_play_draughts(lang: Lang) -> str:
    return tr(lang, en="Post a draughts invite", uk="Надіслати запрошення на шашки", ru="Отправить приглашение на шашки", pl="Wyślij zaproszenie do warcabów")


def command_play_chess(lang: Lang) -> str:
    return tr(lang, en="Post a chess invite", uk="Надіслати запрошення на шахи", ru="Отправить приглашение на шахматы", pl="Wyślij zaproszenie do szachów")


def command_play_robot(lang: Lang) -> str:
    return tr(lang, en="Play draughts against the robot", uk="Зіграти в шашки проти робота", ru="Сыграть в шашки против робота", pl="Zagraj w warcaby przeciw robotowi")


def command_play_chess_robot(lang: Lang) -> str:
    return tr(lang, en="Play chess against the robot", uk="Зіграти в шахи проти робота", ru="Сыграть в шахматы против робота", pl="Zagraj w szachy przeciw robotowi")


def command_play_random(lang: Lang) -> str:
    return tr(lang, en="Play a random global opponent", uk="Зіграти з випадковим глобальним суперником", ru="Сыграть со случайным глобальным соперником", pl="Zagraj z losowym globalnym przeciwnikiem")


def command_cancel_global(lang: Lang) -> str:
    return tr(lang, en="Cancel or resign a global game", uk="Скасувати або здатися у глобальній грі", ru="Отменить глобальную игру или сдаться", pl="Anuluj albo poddaj globalną grę")


def command_resume_global(lang: Lang) -> str:
    return tr(lang, en="Restore your global game message", uk="Відновити повідомлення глобальної гри", ru="Восстановить сообщение глобальной игры", pl="Przywróć wiadomość globalnej gry")


def command_global_stats(lang: Lang) -> str:
    return tr(lang, en="Show global ratings and ranks", uk="Показати глобальні рейтинги та ранги", ru="Показать глобальные рейтинги и ранги", pl="Pokaż globalne rankingi i rangi")


def command_stats(lang: Lang) -> str:
    return tr(lang, en="Show your draughts stats", uk="Показати вашу статистику шашок", ru="Показать вашу статистику шашек", pl="Pokaż swoje statystyki warcabów")


def command_wallet(lang: Lang) -> str:
    return tr(lang, en="Show your kyzma-coins wallet", uk="Показати гаманець кузьмакоінів", ru="Показать кошелёк кузьмакоинов", pl="Pokaż portfel kyzma-coins")


def command_claim(lang: Lang) -> str:
    return tr(lang, en="Claim your daily kyzma-coins", uk="Отримати щоденні кузьмакоіни", ru="Получить ежедневные кузьмакоины", pl="Odbierz dzienne kyzma-coins")


def command_top(lang: Lang) -> str:
    return tr(lang, en="Show the draughts leaderboard", uk="Показати рейтинг гравців", ru="Показать рейтинг игроков", pl="Pokaż ranking graczy")


def command_global_top(lang: Lang) -> str:
    return tr(lang, en="Show the global leaderboard", uk="Показати глобальну таблицю лідерів", ru="Показать глобальную таблицу лидеров", pl="Pokaż globalną tabelę wyników")


def command_feedback(lang: Lang) -> str:
    return tr(lang, en="Send beta feedback", uk="Надіслати відгук про бета-версію", ru="Отправить отзыв о бета-версии", pl="Wyślij opinię o wersji beta")


def command_privacy(lang: Lang) -> str:
    return tr(lang, en="Show the privacy summary", uk="Показати інформацію про конфіденційність", ru="Показать информацию о конфиденциальности", pl="Pokaż informacje o prywatności")


def command_about(lang: Lang) -> str:
    return tr(lang, en="Show bot version and beta status", uk="Показати версію та статус бета", ru="Показать версию и статус бета", pl="Pokaż wersję i status beta")


def command_resign(lang: Lang) -> str:
    return tr(lang, en="Resign a replied-to game", uk="Здатися у грі, на яку ви відповіли", ru="Сдаться в игре, на которую вы ответили", pl="Poddaj grę, na którą odpowiedziano")


def command_list_text(lang: Lang) -> str:
    header = tr(lang, en="Board games available in this bot:", uk="Настільні гри, доступні в цьому боті:", ru="Настольные игры, доступные в этом боте:", pl="Gry planszowe dostępne w tym bocie:")
    lines = [header]
    for name, func_name in COMMANDS:
        lines.append(f"/{name} — {globals()[func_name](lang)}")
    return "\n".join(lines)


def bot_command_descriptions(lang: Lang) -> list[tuple[str, str]]:
    return [(name, globals()[func_name](lang)) for name, func_name in COMMANDS]


def stats_text(lang: Lang, stats: Any | None, game_name: str | None = None) -> str:
    games = getattr(stats, "games_played", 0)
    wins = getattr(stats, "wins", 0)
    losses = getattr(stats, "losses", 0)
    rating = getattr(stats, "rating", 1000)
    current_streak = getattr(stats, "current_streak", 0)
    best_streak = getattr(stats, "best_streak", 0)
    kyzma_balance = STARTER_KYZMA_COINS if stats is None else getattr(stats, "kyzma_coin_balance", STARTER_KYZMA_COINS)
    kyzma_value = kyzma_value_from_rating(rating)
    header = (
        tr(lang, en="🎮 Your draughts stats in this chat", uk="🎮 Ваша статистика шашок у цьому чаті", ru="🎮 Ваша статистика шашек в этом чате", pl="🎮 Twoje statystyki warcabów na tym czacie")
        if game_name is None
        else tr(
            lang,
            en="🎮 Your {game} stats in this chat",
            uk="🎮 Ваша статистика гри {game} у цьому чаті",
            ru="🎮 Ваша статистика игры {game} в этом чате",
            pl="🎮 Twoje statystyki gry {game} na tym czacie",
        ).replace("{game}", game_name)
    )
    return "\n".join([
        header,
        f"{tr(lang, en='Games', uk='Партій', ru='Игр', pl='Gry')}: {games}",
        f"{tr(lang, en='Wins', uk='Перемог', ru='Побед', pl='Wygrane')}: {wins}",
        f"{tr(lang, en='Losses', uk='Поразок', ru='Поражений', pl='Porażki')}: {losses}",
        f"{tr(lang, en='Rating', uk='Рейтинг', ru='Рейтинг', pl='Ranking')}: {rating}",
        f"{kyzma_coin_name(lang)}: {kyzma_balance}",
        f"{tr(lang, en='Game value', uk='Вартість гри', ru='Стоимость игры', pl='Wartość gry')}: {kyzma_value}",
        f"{tr(lang, en='Current streak', uk='Поточна серія', ru='Текущая серия', pl='Aktualna seria')}: {current_streak}",
        f"{tr(lang, en='Best streak', uk='Найкраща серія', ru='Лучшая серия', pl='Najlepsza seria')}: {best_streak}",
    ])


def wallet_text(lang: Lang, stats: Any | None) -> str:
    rating = getattr(stats, "rating", 1000)
    kyzma_balance = STARTER_KYZMA_COINS if stats is None else getattr(stats, "kyzma_coin_balance", STARTER_KYZMA_COINS)
    kyzma_value = kyzma_value_from_rating(rating)
    return "\n".join([
        tr(lang, en="Wallet", uk="Гаманець", ru="Кошелёк", pl="Portfel"),
        f"{kyzma_coin_name(lang)}: {kyzma_balance}",
        f"{tr(lang, en='Game value', uk='Вартість гри', ru='Стоимость игры', pl='Wartość gry')}: {kyzma_value}",
        tr(lang,
            en="Daily bonus: /claim",
            uk="Щоденний бонус: /claim",
            ru="Ежедневный бонус: /claim",
            pl="Dzienny bonus: /claim"),
    ])


def leaderboard_empty(lang: Lang) -> str:
    return tr(lang, en="No draughts games have been completed in this chat yet.", uk="У цьому чаті ще не завершено жодної партії шашок.", ru="В этом чате пока не завершено ни одной партии шашек.", pl="W tym czacie nie zakończono jeszcze żadnej partii warcabów.")


def leaderboard_text(lang: Lang, rows: list[tuple[str, int, int, int]]) -> str:
    header = tr(lang, en="🏆 Draughts leaderboard", uk="🏆 Рейтинг гравців у шашки", ru="🏆 Рейтинг игроков в шашки", pl="🏆 Ranking graczy w warcaby")
    lines = [header]
    for index, (name, wins, losses, rating) in enumerate(rows, start=1):
        lines.append(f"{index}. {name} — {wins}W / {losses}L · {rating} rating")
    return "\n".join(lines)


def rated_header(lang: Lang, rated: bool) -> str:
    if rated:
        return tr(lang, en="Draughts · Rated", uk="Шашки · Рейтингова", ru="Шашки · Рейтинговая", pl="Warcaby · Rankingowa")
    return tr(lang, en="Draughts · Unrated", uk="Шашки · Нерейтингова", ru="Шашки · Нерейтинговая", pl="Warcaby · Towarzyska")


def chess_header(lang: Lang, rated: bool) -> str:
    if rated:
        return tr(lang, en="Chess · Rated", uk="Шахи · Рейтингова", ru="Шахматы · Рейтинговая", pl="Szachy · Rankingowa")
    return tr(lang, en="Chess · Unrated", uk="Шахи · Нерейтингова", ru="Шахматы · Нерейтинговая", pl="Szachy · Towarzyska")


def draughts_invite_header(lang: Lang) -> str:
    return tr(lang, en="Draughts invite", uk="Запрошення на шашки", ru="Приглашение на шашки", pl="Zaproszenie do warcabów")


def chess_invite_header(lang: Lang) -> str:
    return tr(lang, en="Chess invite", uk="Запрошення на шахи", ru="Приглашение на шахматы", pl="Zaproszenie do szachów")


def chess_game_name(lang: Lang) -> str:
    return tr(lang, en="chess", uk="шахи", ru="шахматы", pl="szachy")


def color_label(lang: Lang, color: PieceColor) -> str:
    if color is PieceColor.BLACK:
        return tr(lang, en="Black", uk="Чорні", ru="Чёрные", pl="Czarne")
    return tr(lang, en="White", uk="Білі", ru="Белые", pl="Białe")


def move_line(lang: Lang, move_number: int) -> str:
    return f"{tr(lang, en='Move', uk='Хід', ru='Ход', pl='Ruch')}: {move_number}"


def turn_line(lang: Lang, name: str, symbol: str) -> str:
    return f"{tr(lang, en='Turn', uk='Хід', ru='Ход', pl='Tura')}: {name} — {symbol}"


def game_over_header(lang: Lang) -> str:
    return tr(lang, en="🏁 Game over", uk="🏁 Гру завершено", ru="🏁 Игра завершена", pl="🏁 Koniec gry")


def winner_line(lang: Lang, name: str, symbol: str) -> str:
    return f"{tr(lang, en='Winner', uk='Переможець', ru='Победитель', pl='Zwycięzca')}: {name} {symbol}"


def winner_draw_line(lang: Lang) -> str:
    return tr(lang, en="Winner: Draw", uk="Переможець: Нічия", ru="Победитель: Ничья", pl="Zwycięzca: Remis")


def reason_line(lang: Lang, reason: str) -> str:
    return f"{tr(lang, en='Reason', uk='Причина', ru='Причина', pl='Powód')}: {reason}"


def rematch_offer_line(lang: Lang, requester_name: str) -> str:
    return tr(lang,
        en='🔁 {name} wants a rematch. Tap "Accept rematch" to start!',
        uk="🔁 {name} пропонує реванш. Натисніть «Прийняти реванш», щоб почати!",
        ru="🔁 {name} предлагает реванш. Нажмите «Принять реванш», чтобы начать!",
        pl="🔁 {name} proponuje rewanż. Naciśnij „Przyjmij rewanż”, aby zacząć!").replace("{name}", requester_name)


def reason_no_legal_moves(lang: Lang, loser_label: str) -> str:
    return f"{loser_label} {tr(lang, en='has no legal moves', uk='не має допустимих ходів', ru='не имеет допустимых ходов', pl='nie ma dozwolonych ruchów')}"


def reason_no_pieces(lang: Lang, loser_label: str) -> str:
    return f"{loser_label} {tr(lang, en='has no pieces', uk='не має фігур', ru='не имеет фигур', pl='nie ma pionków')}"


def player_word(lang: Lang) -> str:
    return tr(lang, en="Player", uk="Гравець", ru="Игрок", pl="Gracz")


def reason_resignation(lang: Lang) -> str:
    return tr(lang, en="Resignation", uk="Здача", ru="Сдача", pl="Poddanie się")


def kyzma_coin_name(lang: Lang) -> str:
    return tr(lang, en="kyzma-coins", uk="кузьмакоін", ru="кузьмакоин", pl="kyzma-coins")


def kyzma_prize_line(lang: Lang, base: int, multiplier: int, prize: int) -> str:
    label = tr(lang, en="Prize", uk="Приз", ru="Приз", pl="Nagroda")
    return f"{label}: {base} {kyzma_coin_name(lang)} ×{multiplier} = {prize}"


def kyzma_game_cost_line(lang: Lang, cost: int) -> str:
    label = tr(lang, en="Game cost", uk="Вартість гри", ru="Стоимость игры", pl="Koszt gry")
    return f"{label}: {cost} {kyzma_coin_name(lang)}"


def kyzma_entry_fee_notice(lang: Lang) -> str:
    return tr(lang,
        en="Both players are charged this cost when the game starts.",
        uk="З обох гравців буде списано цю суму, коли гра почнеться.",
        ru="С обоих игроков будет списана эта сумма, когда игра начнётся.",
        pl="Obaj gracze zapłacą ten koszt po rozpoczęciu gry.")


def daily_claim_success(lang: Lang, amount: int, balance: int) -> str:
    return tr(lang,
        en="Daily bonus claimed: +{amount} {coin}.\nBalance: {balance} {coin}.",
        uk="Щоденний бонус отримано: +{amount} {coin}.\nБаланс: {balance} {coin}.",
        ru="Ежедневный бонус получен: +{amount} {coin}.\nБаланс: {balance} {coin}.",
        pl="Dzienny bonus odebrany: +{amount} {coin}.\nSaldo: {balance} {coin}.",
    ).replace("{amount}", str(amount)).replace("{balance}", str(balance)).replace("{coin}", kyzma_coin_name(lang))


def daily_claim_already_claimed(lang: Lang, balance: int) -> str:
    return tr(lang,
        en="You already claimed today's daily bonus.\nBalance: {balance} {coin}.",
        uk="Ви вже отримали сьогоднішній щоденний бонус.\nБаланс: {balance} {coin}.",
        ru="Вы уже получили сегодняшний ежедневный бонус.\nБаланс: {balance} {coin}.",
        pl="Dzisiejszy bonus dzienny jest już odebrany.\nSaldo: {balance} {coin}.",
    ).replace("{balance}", str(balance)).replace("{coin}", kyzma_coin_name(lang))


def player_value_line(lang: Lang, value: int) -> str:
    label = tr(lang, en="Game value", uk="Вартість гри", ru="Стоимость игры", pl="Wartość gry")
    return f"{label}: {value}"


def confirm_game_header(lang: Lang) -> str:
    return tr(lang, en="Confirm rated game", uk="Підтвердьте рейтингову гру", ru="Подтвердите рейтинговую игру", pl="Potwierdź grę rankingową")


def confirm_chess_game_header(lang: Lang) -> str:
    return tr(lang, en="Confirm rated chess game", uk="Підтвердьте рейтингову гру в шахи", ru="Подтвердите рейтинговую игру в шахматы", pl="Potwierdź rankingową grę w szachy")


def both_players_must_accept(lang: Lang) -> str:
    return tr(lang, en="Both players must accept before the game starts.", uk="Обидва гравці мають підтвердити перед початком гри.", ru="Оба игрока должны подтвердить перед началом игры.", pl="Obaj gracze muszą zaakceptować przed startem gry.")


def accepted_count_line(lang: Lang, accepted: int, total: int) -> str:
    label = tr(lang, en="Accepted", uk="Підтверджено", ru="Подтверждено", pl="Zaakceptowano")
    return f"{label}: {accepted}/{total}"


def inline_article_title(lang: Lang) -> str:
    return tr(lang, en="Play Draughts", uk="Зіграти в шашки", ru="Сыграть в шашки", pl="Zagraj w warcaby")


def inline_article_description(lang: Lang) -> str:
    return tr(lang, en="Post a draughts invite in this chat", uk="Надіслати запрошення на шашки в цьому чаті", ru="Отправить приглашение на шашки в этом чате", pl="Wyślij zaproszenie do warcabów na tym czacie")


def waiting_for_opponent(lang: Lang) -> str:
    return tr(lang, en="Waiting for opponent...", uk="Очікування суперника...", ru="Ожидание соперника...", pl="Czekanie na przeciwnika...")


def join_as_white_button(lang: Lang) -> str:
    return tr(lang, en="Join as White", uk="Приєднатися як білі", ru="Присоединиться как белые", pl="Dołącz jako białe")


def join_rated_button(lang: Lang) -> str:
    return tr(lang, en="Join rated", uk="Приєднатися рейтингово", ru="Присоединиться рейтингово", pl="Dołącz rankingowo")


def join_unrated_button(lang: Lang) -> str:
    return tr(lang, en="Join unrated", uk="Приєднатися без рейтингу", ru="Присоединиться без рейтинга", pl="Dołącz towarzysko")


def accept_game_button(lang: Lang) -> str:
    return tr(lang, en="Accept", uk="Підтвердити", ru="Подтвердить", pl="Akceptuj")


def robot_difficulty_prompt(lang: Lang) -> str:
    return tr(lang, en="Choose robot difficulty:", uk="Виберіть складність робота:", ru="Выберите сложность робота:", pl="Wybierz poziom robota:")


def chess_robot_difficulty_prompt(lang: Lang) -> str:
    return tr(lang, en="Choose chess robot difficulty:", uk="Виберіть складність шахового робота:", ru="Выберите сложность шахматного робота:", pl="Wybierz poziom robota szachowego:")


def robot_easy_button(lang: Lang) -> str:
    return tr(lang, en="Easy", uk="Легко", ru="Легко", pl="Łatwy")


def robot_normal_button(lang: Lang) -> str:
    return tr(lang, en="Normal", uk="Нормально", ru="Нормально", pl="Normalny")


def robot_hard_button(lang: Lang) -> str:
    return tr(lang, en="Hard", uk="Складно", ru="Сложно", pl="Trudny")


def resign_button(lang: Lang) -> str:
    return tr(lang, en="Resign", uk="Здатися", ru="Сдаться", pl="Poddaj się")


def stats_button(lang: Lang) -> str:
    return tr(lang, en="Stats", uk="Статистика", ru="Статистика", pl="Statystyki")


def play_again_button(lang: Lang) -> str:
    return tr(lang, en="Play again", uk="Зіграти ще раз", ru="Сыграть ещё раз", pl="Zagraj jeszcze raz")


def accept_rematch_button(lang: Lang) -> str:
    return tr(lang, en="Accept rematch", uk="Прийняти реванш", ru="Принять реванш", pl="Przyjmij rewanż")


def check_line(lang: Lang) -> str:
    return tr(lang, en="Check", uk="Шах", ru="Шах", pl="Szach")


def promote_to(lang: Lang) -> str:
    return tr(lang, en="Promote to", uk="Перетворити на", ru="Превратить в", pl="Promuj na")


def queen_button(lang: Lang) -> str:
    return tr(lang, en="Queen", uk="Ферзь", ru="Ферзь", pl="Hetman")


def rook_button(lang: Lang) -> str:
    return tr(lang, en="Rook", uk="Тура", ru="Ладья", pl="Wieża")


def bishop_button(lang: Lang) -> str:
    return tr(lang, en="Bishop", uk="Слон", ru="Слон", pl="Goniec")


def knight_button(lang: Lang) -> str:
    return tr(lang, en="Knight", uk="Кінь", ru="Конь", pl="Skoczek")


generic_error = lambda lang: tr(lang, en="Something went wrong. Please try again.", uk="Щось пішло не так. Спробуйте ще раз.", ru="Что-то пошло не так. Попробуйте ещё раз.", pl="Coś poszło nie tak. Spróbuj ponownie.")
button_no_action = lambda lang: tr(lang, en="This button has no action.", uk="Ця кнопка не має дії.", ru="У этой кнопки нет действия.", pl="Ten przycisk nie ma akcji.")
unrecognized_action = lambda lang: tr(lang, en="I don't recognize that draughts action.", uk="Не розпізнаю цю дію в шашках.", ru="Не распознаю это действие в шашках.", pl="Nie rozpoznaję tej akcji w warcabach.")
button_no_context = lambda lang: tr(lang, en="This button has no context.", uk="Ця кнопка не має контексту.", ru="У этой кнопки нет контекста.", pl="Ten przycisk nie ma kontekstu.")
inline_only_button = lambda lang: tr(lang, en="That button only works on inline messages.", uk="Ця кнопка працює лише в інлайн-повідомленнях.", ru="Эта кнопка работает только во встроенных сообщениях.", pl="Ten przycisk działa tylko w wiadomościach inline.")
post_new_invite_to_join = lambda lang: tr(lang, en="Post a new invite to join.", uk="Надішліть нове запрошення, щоб приєднатися.", ru="Отправьте новое приглашение, чтобы присоединиться.", pl="Wyślij nowe zaproszenie, aby dołączyć.")
game_not_found = lambda lang: tr(lang, en="I can't find that game anymore.", uk="Не можу знайти цю гру.", ru="Не могу найти эту игру.", pl="Nie mogę znaleźć tej gry.")
wrong_game_kind = lambda lang: tr(lang, en="That button is not for a draughts game.", uk="Ця кнопка не для гри в шашки.", ru="Эта кнопка не для игры в шашки.", pl="Ten przycisk nie jest dla gry w warcaby.")
wrong_chess_game_kind = lambda lang: tr(lang, en="That button is not for a chess game.", uk="Ця кнопка не для гри в шахи.", ru="Эта кнопка не для игры в шахматы.", pl="Ten przycisk nie jest dla gry w szachy.")
game_already_over = lambda lang: tr(lang, en="That game is already over.", uk="Ця гра вже закінчена.", ru="Эта игра уже закончилась.", pl="Ta gra już się zakończyła.")
game_not_started = lambda lang: tr(lang, en="That game has not started yet.", uk="Ця гра ще не почалася.", ru="Эта игра ещё не началась.", pl="Ta gra jeszcze się nie zaczęła.")
game_not_waiting_for_accept = lambda lang: tr(lang, en="That game is not waiting for confirmation.", uk="Ця гра не очікує підтвердження.", ru="Эта игра не ждёт подтверждения.", pl="Ta gra nie czeka na potwierdzenie.")
only_players_can_accept = lambda lang: tr(lang, en="Only the two players can accept this game.", uk="Підтвердити цю гру можуть лише два гравці.", ru="Подтвердить эту игру могут только два игрока.", pl="Tylko dwaj gracze mogą zaakceptować tę grę.")
game_accept_recorded = lambda lang: tr(lang, en="Accepted. Waiting for the other player.", uk="Підтверджено. Чекаємо на іншого гравця.", ru="Подтверждено. Ждём второго игрока.", pl="Zaakceptowano. Czekamy na drugiego gracza.")
game_accept_waiting = lambda lang: tr(lang, en="Already accepted. Waiting for the other player.", uk="Вже підтверджено. Чекаємо на іншого гравця.", ru="Уже подтверждено. Ждём второго игрока.", pl="Już zaakceptowano. Czekamy na drugiego gracza.")
game_started = lambda lang: tr(lang, en="Game started.", uk="Гру розпочато.", ru="Игра началась.", pl="Gra rozpoczęta.")
not_enough_kyzma_coins = lambda lang, cost: tr(lang,
    en="Rated game costs {cost} {coin}. Both players need enough balance.",
    uk="Рейтингова гра коштує {cost} {coin}. В обох гравців має вистачати балансу.",
    ru="Рейтинговая игра стоит {cost} {coin}. У обоих игроков должен быть достаточный баланс.",
    pl="Gra rankingowa kosztuje {cost} {coin}. Obaj gracze muszą mieć wystarczające saldo.").replace("{cost}", str(cost)).replace("{coin}", kyzma_coin_name(lang))
not_your_turn = lambda lang: tr(lang, en="It's not your turn.", uk="Це не ваш хід.", ru="Это не ваш ход.", pl="To nie twoja tura.")
move_unavailable = lambda lang: tr(lang, en="That move is no longer available.", uk="Цей хід більше не доступний.", ru="Этот ход больше не доступен.", pl="Ten ruch nie jest już dostępny.")
move_illegal = lambda lang: tr(lang, en="That move is no longer legal.", uk="Цей хід більше не є допустимим.", ru="Этот ход больше не является допустимым.", pl="Ten ruch nie jest już dozwolony.")
opponents_piece = lambda lang: tr(lang, en="That is your opponent's piece.", uk="Це фігура вашого суперника.", ru="Это фигура вашего соперника.", pl="To pionek twojego przeciwnika.")
must_continue_capture = lambda lang: tr(lang, en="You must continue capturing with the same piece.", uk="Ви повинні продовжити взяття тією ж фігурою.", ru="Вы должны продолжить взятие той же фигурой.", pl="Musisz kontynuować bicie tym samym pionkiem.")
capture_mandatory = lambda lang: tr(lang, en="A capture is mandatory. Choose a piece that can capture.", uk="Взяття обов'язкове. Виберіть фігуру, яка може бити.", ru="Взятие обязательно. Выберите фигуру, которая может бить.", pl="Bicie jest obowiązkowe. Wybierz pionek, który może bić.")
piece_no_legal_moves = lambda lang: tr(lang, en="That piece has no legal moves.", uk="Ця фігура не має допустимих ходів.", ru="Эта фигура не имеет допустимых ходов.", pl="Ten pionek nie ma dozwolonych ruchów.")
only_player_can_resign = lambda lang: tr(lang, en="Only a player in this game can resign.", uk="Здатися може лише гравець цієї партії.", ru="Сдаться может только игрок этой партии.", pl="Poddać się może tylko gracz tej partii.")
stats_group_only = lambda lang: tr(lang, en="Stats are available in group chats. Use /stats there.", uk="Статистика доступна лише в групових чатах. Скористайтеся /stats там.", ru="Статистика доступна только в групповых чатах. Используйте /stats там.", pl="Statystyki są dostępne tylko na czatach grupowych. Użyj tam /stats.")
bots_cannot_join = lambda lang: tr(lang, en="Bots can't join draughts games.", uk="Боти не можуть приєднуватися до гри в шашки.", ru="Боты не могут присоединяться к игре в шашки.", pl="Boty nie mogą przyłączać się do gry w warcaby.")
bots_cannot_join_chess = lambda lang: tr(lang, en="Bots can't join chess games.", uk="Боти не можуть приєднуватися до гри в шахи.", ru="Боты не могут присоединяться к игре в шахматы.", pl="Boty nie mogą przyłączać się do gry w szachy.")
invite_invalid_create = lambda lang: tr(lang, en="This invite is invalid. Please create a new one.", uk="Це запрошення недійсне. Будь ласка, створіть нове.", ru="Это приглашение недействительно. Пожалуйста, создайте новое.", pl="To zaproszenie jest nieprawidłowe. Utwórz nowe.")
invite_invalid_post = lambda lang: tr(lang, en="This invite is invalid. Please post a new one.", uk="Це запрошення недійсне. Будь ласка, надішліть нове.", ru="Это приглашение недействительно. Пожалуйста, отправьте новое.", pl="To zaproszenie jest nieprawidłowe. Wyślij nowe.")
cannot_join_own_invite = lambda lang: tr(lang, en="You can't join your own invite.", uk="Ви не можете приєднатися до власного запрошення.", ru="Вы не можете присоединиться к собственному приглашению.", pl="Nie możesz dołączyć do własnego zaproszenia.")
invite_already_started = lambda lang: tr(lang, en="This invite has already started a game.", uk="За цим запрошенням гру вже розпочато.", ru="По этому приглашению игра уже началась.", pl="Ta gra na podstawie tego zaproszenia już się zaczęła.")
invite_expired_create = lambda lang: tr(lang, en="This invite expired. Ask them to create a new one.", uk="Це запрошення застаріло. Попросіть створити нове.", ru="Это приглашение устарело. Попросите создать новое.", pl="To zaproszenie wygasło. Poproś o utworzenie nowego.")
invite_expired_post = lambda lang: tr(lang, en="This invite expired. Ask them to post a new one.", uk="Це запрошення застаріло. Попросіть надіслати нове.", ru="Это приглашение устарело. Попросите отправить новое.", pl="To zaproszenie wygasło. Poproś o wysłanie nowego.")
invite_no_longer_valid = lambda lang: tr(lang, en="This invite is no longer valid.", uk="Це запрошення більше не дійсне.", ru="Это приглашение больше не действительно.", pl="To zaproszenie nie jest już ważne.")
rematch_offer_sent = lambda lang: tr(lang, en="Rematch offer sent. Waiting for your opponent to accept.", uk="Пропозицію реваншу надіслано. Чекаємо на згоду суперника.", ru="Предложение реванша отправлено. Ждём согласия соперника.", pl="Propozycja rewanżu wysłana. Czekamy na zgodę przeciwnika.")
rematch_waiting_for_opponent = lambda lang: tr(lang, en="Waiting for your opponent to accept your rematch offer.", uk="Очікуємо, поки суперник прийме вашу пропозицію реваншу.", ru="Ждём, пока соперник примет ваше предложение реванша.", pl="Czekamy, aż przeciwnik zaakceptuje twoją propozycję rewanżu.")
finish_before_rematch = lambda lang: tr(lang, en="Finish this game before starting a rematch.", uk="Завершіть цю гру перед початком реваншу.", ru="Завершите эту игру перед началом реванша.", pl="Zakończ tę grę, zanim zaczniesz rewanż.")
only_players_can_rematch = lambda lang: tr(lang, en="Only the players in this game can start a rematch.", uk="Розпочати реванш можуть лише гравці цієї партії.", ru="Начать реванш могут только игроки этой партии.", pl="Rewanż mogą zacząć tylko gracze tej partii.")
resign_reply_required = lambda lang: tr(lang, en="Reply to an active draughts board message with /resign.", uk="Відповідайте командою /resign на повідомлення з активною партією.", ru="Ответьте командой /resign на сообщение с активной партией.", pl="Odpowiedz komendą /resign na wiadomość z aktywną partią.")
no_active_game_on_message = lambda lang: tr(lang, en="I couldn't find an active game on that message.", uk="Не вдалося знайти активну гру в цьому повідомленні.", ru="Не удалось найти активную игру в этом сообщении.", pl="Nie znalazłem aktywnej gry w tej wiadomości.")
replied_game_not_draughts = lambda lang: tr(lang, en="That replied-to game is not draughts.", uk="Гра в цьому повідомленні — не шашки.", ru="Игра в этом сообщении — не шашки.", pl="Gra w tej wiadomości to nie warcaby.")
not_playing_in_game = lambda lang: tr(lang, en="You're not playing in that game.", uk="Ви не берете участь у цій грі.", ru="Вы не участвуете в этой игре.", pl="Nie grasz w tej grze.")
game_resigned = lambda lang: tr(lang, en="Game resigned.", uk="Гру завершено здачею.", ru="Игра завершена сдачей.", pl="Gra zakończona poddaniem się.")
