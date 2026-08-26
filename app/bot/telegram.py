from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.bot.handlers import TelegramHandlers
from app.config import Settings

logger = logging.getLogger(__name__)


def build_application(settings: Settings):
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required to run the Telegram bot")
    application = Application.builder().token(settings.telegram_bot_token).build()
    handlers = TelegramHandlers(settings, application.bot)

    commands = {
        "start": handlers.start,
        "help": handlers.help,
        "menu": handlers.menu,
        "approve": handlers.approve,
        "regenerate": handlers.regenerate,
        "recipes": handlers.recipes,
        "recipe": handlers.recipe,
        "addrecipe": handlers.add_recipe,
        "deleterecipe": handlers.delete_recipe,
        "preferences": handlers.preferences,
        "addpreference": handlers.add_preference,
        "deletepreference": handlers.delete_preference,
        "history": handlers.history,
        "shopping": handlers.shopping,
        "pantry": handlers.pantry,
        "pantryadd": handlers.pantry_add,
        "pantryremove": handlers.pantry_remove,
    }
    for name, callback in commands.items():
        application.add_handler(CommandHandler(name, callback))
    application.add_handler(CallbackQueryHandler(handlers.callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text))
    return application


class TelegramBotNotifier:
    def __init__(self, bot):
        self.bot = bot

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text, **kwargs)

