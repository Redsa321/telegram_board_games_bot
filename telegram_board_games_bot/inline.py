from __future__ import annotations

from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.ext import ContextTypes

from . import i18n
from .commands import display_name, get_database, telegram_user_id, upsert_user_from_telegram
from .render.text_board import render_draughts_inline_invite_keyboard, render_draughts_invite_message


async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if query is None:
        return
    database = get_database(context)
    await database.upsert_user(upsert_user_from_telegram(query.from_user))
    challenger_id = telegram_user_id(query.from_user)
    lang = i18n.user_lang(query.from_user)
    article = InlineQueryResultArticle(
        id="draughts",
        title=i18n.inline_article_title(lang),
        description=i18n.inline_article_description(lang),
        input_message_content=InputTextMessageContent(render_draughts_invite_message(display_name(query.from_user), lang)),
        reply_markup=render_draughts_inline_invite_keyboard(challenger_id, lang),
    )
    await query.answer([article], cache_time=0)


async def handle_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.chosen_inline_result
    if result is None or result.inline_message_id is None:
        return
    database = get_database(context)
    challenger_id = telegram_user_id(result.from_user)
    await database.upsert_user(upsert_user_from_telegram(result.from_user))
    await database.create_inline_invite(result.inline_message_id, challenger_id)

