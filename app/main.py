from __future__ import annotations

import asyncio
import logging

import uvicorn

from app.bot.telegram import build_application
from app.config import get_settings
from app.db.session import init_db
from app.logging_config import configure_logging
from app.scheduler.weekly import build_scheduler
from app.web_panel import create_web_app

logger = logging.getLogger(__name__)


async def async_main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    application = build_application(settings)
    scheduler = build_scheduler(settings, bot=application.bot)
    web_server = None
    web_task = None
    if settings.web_panel_enabled:
        web_server = uvicorn.Server(
            uvicorn.Config(
                create_web_app(settings),
                host=settings.web_panel_host,
                port=settings.web_panel_port,
                log_level="warning",
                access_log=False,
            )
        )
        web_task = asyncio.create_task(web_server.serve())
        logger.info("web_panel_started host=%s port=%s", settings.web_panel_host, settings.web_panel_port)
    api_server = _app_api_server(settings, application.bot)
    api_task = asyncio.create_task(api_server.serve()) if api_server is not None else None
    scheduler.start()
    logger.info("application_started")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    try:
        await asyncio.Event().wait()
    finally:
        if web_server:
            web_server.should_exit = True
        if web_task:
            await web_task
        if api_server is not None:
            api_server.should_exit = True
            await api_task
        scheduler.shutdown(wait=False)
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def _app_api_server(settings, bot):
    """Foody uygulamasinin HTTPS API'si. Eksik ayar botu durdurmaz: Telegram
    calismaya devam eder, sebep gunluge yazilir."""
    if not settings.app_api_enabled:
        return None
    from app.api import MIN_TOKEN_LENGTH, create_api_app
    from app.bot.telegram import TelegramBotNotifier

    problems = []
    if len(settings.app_api_token) < MIN_TOKEN_LENGTH:
        problems.append("APP_API_TOKEN kisa ya da yok")
    if not (settings.app_api_cert.exists() and settings.app_api_key.exists()):
        problems.append("sertifika yok")
    if problems:
        logger.error("app_api_not_started reason=%s fix='python -m app.cli uygulama-hazirla --adres https://...'",
                     ", ".join(problems))
        return None
    server = uvicorn.Server(
        uvicorn.Config(
            create_api_app(settings, notifier=TelegramBotNotifier(bot)),
            host=settings.app_api_host,
            port=settings.app_api_port,
            ssl_certfile=str(settings.app_api_cert),
            ssl_keyfile=str(settings.app_api_key),
            log_level="warning",
            access_log=False,
        )
    )
    logger.info("app_api_started host=%s port=%s", settings.app_api_host, settings.app_api_port)
    return server


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
