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
        scheduler.shutdown(wait=False)
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
