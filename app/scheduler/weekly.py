from __future__ import annotations

import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot.keyboards import approval_keyboard
from app.config import Settings
from app.db.session import SessionLocal
from app.formatting import format_meal_plan
from app.planner.service import MealPlannerService

logger = logging.getLogger(__name__)
_CURRENT_BOT = None

DAY_ALIASES = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}


def build_scheduler(settings: Settings, bot=None) -> AsyncIOScheduler:
    global _CURRENT_BOT
    _CURRENT_BOT = bot
    jobstores = {"default": SQLAlchemyJobStore(url=settings.database_url)}
    scheduler = AsyncIOScheduler(timezone=settings.timezone, jobstores=jobstores)
    hour, minute = settings.weekly_plan_time.split(":", maxsplit=1)
    scheduler.add_job(
        weekly_plan_job,
        trigger=CronTrigger(
            day_of_week=DAY_ALIASES.get(settings.weekly_plan_day.casefold(), settings.weekly_plan_day[:3]),
            hour=int(hour),
            minute=int(minute),
            timezone=settings.timezone,
        ),
        id="weekly_meal_plan",
        replace_existing=True,
        kwargs={"settings_values": settings.model_dump(mode="json")},
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    return scheduler


async def weekly_plan_job(settings_values: dict) -> None:
    settings = Settings.model_validate(settings_values)
    logger.info("weekly_plan_started")
    with SessionLocal() as db:
        session = await MealPlannerService(db, settings).create_or_get_weekly_session()
        if _CURRENT_BOT and settings.admin_telegram_user_id:
            await _CURRENT_BOT.send_message(
                chat_id=settings.admin_telegram_user_id,
                text=f"🍽️ Önümüzdeki haftanın yemek planını hazırladım.\n\n{format_meal_plan(session)}",
                parse_mode="Markdown",
                reply_markup=approval_keyboard(),
            )
            logger.info("draft_sent_to_admin session_id=%s", session.id)
