from __future__ import annotations

from dataclasses import replace
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import i18n
from .commands import (
    GAME_KIND_CHESS,
    GAME_KIND_DRAUGHTS,
    display_name_from_parts,
    get_database,
    render_stats_text,
    stats_display_name,
    telegram_user_id,
    upsert_chat_from_telegram,
    upsert_user_from_telegram,
)
from .global_matchmaking import global_game_stats_text

SCOPES = {"local", "global"}
GAME_KINDS = {GAME_KIND_DRAUGHTS, GAME_KIND_CHESS}
VIEWS = {"stats", "top"}


async def handle_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_stats_menu(update, context, "local", GAME_KIND_DRAUGHTS)


async def handle_global_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_stats_menu(update, context, "global", GAME_KIND_DRAUGHTS)


async def handle_top_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_top_menu(update, context, "local", GAME_KIND_DRAUGHTS)


async def handle_global_top_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_top_menu(update, context, "global", GAME_KIND_DRAUGHTS)


async def send_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, scope: str, game_kind: str) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    database = get_database(context)
    await database.upsert_user(upsert_user_from_telegram(user))
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    text = await stats_view_text(database, message.chat_id, user, scope, game_kind)
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=selector_keyboard("stats", scope, game_kind),
        reply_parameters=ReplyParameters(message_id=message.message_id),
    )


async def send_top_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, scope: str, game_kind: str) -> None:
    message = update.effective_message
    if message is None:
        return
    database = get_database(context)
    if update.effective_chat:
        await database.upsert_chat(upsert_chat_from_telegram(update.effective_chat))
    text = await leaderboard_view_text(database, message.chat_id, i18n.user_lang(update.effective_user), scope, game_kind)
    await message.reply_text(text, reply_markup=selector_keyboard("top", scope, game_kind))


async def handle_stats_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    parsed = parse_selector_data(query.data)
    if parsed is None:
        await query.answer("This stats selection is no longer valid.")
        return
    view, scope, game_kind = parsed
    await query.answer()
    database = get_database(context)
    user = query.from_user
    if view == "stats":
        await database.upsert_user(upsert_user_from_telegram(user))
        text = await stats_view_text(database, query.message.chat_id, user, scope, game_kind)
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=selector_keyboard(view, scope, game_kind),
        )
        return
    text = await leaderboard_view_text(database, query.message.chat_id, i18n.user_lang(user), scope, game_kind)
    await query.edit_message_text(text, reply_markup=selector_keyboard(view, scope, game_kind))


async def stats_view_text(database, chat_id: int, user, scope: str, game_kind: str) -> str:
    user_id = telegram_user_id(user)
    wallet = await database.ensure_global_wallet(user_id)
    if scope == "global":
        stats = await database.ensure_global_user_stats(user_id, game_kind)
        return global_game_stats_text(game_kind, stats, wallet.kyzma_coin_balance, escape(stats_display_name(user)))
    stats = await database.ensure_user_stats(chat_id, user_id, game_kind)
    stats = replace(stats, kyzma_coin_balance=wallet.kyzma_coin_balance)
    return render_stats_text(i18n.user_lang(user), stats, user, game_kind.title())


async def leaderboard_view_text(database, chat_id: int, lang, scope: str, game_kind: str) -> str:
    entries = (
        await database.get_global_leaderboard(game_kind, 10)
        if scope == "global"
        else await database.get_group_leaderboard(chat_id, game_kind, 10)
    )
    title = f"{'Global' if scope == 'global' else 'Chat'} {game_kind.title()} leaderboard"
    if not entries:
        return f"{title}\nNo completed rated games yet."
    lines = [title]
    for index, entry in enumerate(entries, start=1):
        name = display_name_from_parts(entry.username, entry.first_name, entry.last_name, entry.user_id)
        lines.append(
            f"{index}. {name} · {entry.rating} rating · "
            f"{entry.wins}W/{entry.losses}L/{entry.draws}D"
        )
    return "\n".join(lines)


def selector_keyboard(view: str, scope: str, game_kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(selected_label("This chat", scope == "local"), callback_data=selector_data(view, "local", game_kind)),
            InlineKeyboardButton(selected_label("Global", scope == "global"), callback_data=selector_data(view, "global", game_kind)),
        ],
        [
            InlineKeyboardButton(selected_label("Draughts", game_kind == GAME_KIND_DRAUGHTS), callback_data=selector_data(view, scope, GAME_KIND_DRAUGHTS)),
            InlineKeyboardButton(selected_label("Chess", game_kind == GAME_KIND_CHESS), callback_data=selector_data(view, scope, GAME_KIND_CHESS)),
        ],
    ])


def selector_data(view: str, scope: str, game_kind: str) -> str:
    return f"st:{view}:{scope}:{game_kind}"


def parse_selector_data(data: str) -> tuple[str, str, str] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "st":
        return None
    if parts[1] not in VIEWS or parts[2] not in SCOPES or parts[3] not in GAME_KINDS:
        return None
    return parts[1], parts[2], parts[3]


def selected_label(label: str, selected: bool) -> str:
    return f"✓ {label}" if selected else label
