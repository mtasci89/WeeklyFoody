from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.bot.handlers import TelegramHandlers
from app.config import Settings

logger = logging.getLogger(__name__)


def build_application(settings: Settings):
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required to run the Telegram bot")
    async def setup_commands(application):
        await application.bot.set_my_commands([BotCommand("menu", "Menüyü gör ve düzenle"), BotCommand("shopping", "Alışveriş listesi"), BotCommand("recipes", "Tarif kütüphanesi"), BotCommand("regenerate", "Yeni menü hazırla"), BotCommand("help", "Kullanım örnekleri")])
    application = Application.builder().token(settings.telegram_bot_token).post_init(setup_commands).build()
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
        "discover": handlers.discover,
        "candidates": handlers.candidates,
        "approverecipe": handlers.approve_recipe_candidate,
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
    async def on_error(update, context):
        logger.error("telegram_handler_failed", exc_info=context.error)
        if update and update.effective_message:
            from app.bot.messages import reply
            text = str(context.error) if isinstance(context.error, ValueError) else "İşlemi tamamlayamadım. Menüye /menu ile bakıp tekrar deneyebilirsin. Gönderim yarıda kaldıysa /approve ile kaldığı yerden devam edebilirsin."
            await reply(update.effective_message, text)
    application.add_error_handler(on_error)
    return application


class TelegramBotNotifier:
    def __init__(self, bot):
        self.bot = bot

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text, **kwargs)

