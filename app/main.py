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
    # Telegram'a o an ulaşılamaması uygulama API'sini düşürmesin: eskiden burada atılan
    # hata tüm süreci kapatıyor, servis 15 sn'de bir yeniden başlarken uygulama
    # "sunucuya ulaşılamadı" alıyordu.
    telegram_task = asyncio.create_task(start_telegram(application, settings))
    try:
        await asyncio.Event().wait()
    finally:
        telegram_task.cancel()
        if web_server:
            web_server.should_exit = True
        if web_task:
            await web_task
        if api_server is not None:
            api_server.should_exit = True
            await api_task
        scheduler.shutdown(wait=False)
        await _stop_telegram(application)


async def start_telegram(application, settings, first_delay: float = 10, max_delay: float = 600) -> bool:
    """Telegram botunu başlatır; ağ hatasında artan aralıklarla yeniden dener."""
    delay = first_delay
    while True:
        try:
            await application.initialize()
            if not application.running:
                await application.start()
            if not application.updater.running:
                await application.updater.start_polling()
            logger.info("telegram_started")
            await _announce_update(settings, application.bot)
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telegram_start_failed retry_in=%s", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)


async def _stop_telegram(application) -> None:
    for step in (
        lambda: application.updater.stop() if application.updater.running else None,
        lambda: application.stop() if application.running else None,
        application.shutdown,
    ):
        try:
            result = step()
            if result is not None:
                await result
        except Exception:
            logger.exception("telegram_stop_failed")


async def _announce_update(settings, bot) -> None:
    """Telefondan başlatılan bir güncellemeden sonra açıldıysak sonucu bildir."""
    from app.updater import pending_notice

    notice = pending_notice()
    if notice is None:
        return
    chat_id, text = notice
    try:
        await bot.send_message(chat_id=chat_id or settings.admin_telegram_user_id, text=text)
    except Exception:
        logger.exception("update_notice_failed")


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
            # Uygulama bağlantıyı 30 sn boşta tutar; sunucu daha önce kapatıp yarış yaratmasın.
            timeout_keep_alive=75,
        )
    )
    logger.info("app_api_started host=%s port=%s", settings.app_api_host, settings.app_api_port)
    return server


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
