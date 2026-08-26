from __future__ import annotations

import asyncio
import logging

from app.bot.telegram import build_application
from app.config import get_settings
from app.db.session import init_db
from app.logging_config import configure_logging
from app.scheduler.weekly import build_scheduler

logger = logging.getLogger(__name__)


async def async_main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    application = build_application(settings)
    scheduler = build_scheduler(settings, bot=application.bot)
    scheduler.start()
    logger.info("application_started")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

