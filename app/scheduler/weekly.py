from __future__ import annotations

import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot.keyboards import approval_keyboard
from app.config import Settings
from app.db.session import SessionLocal
from app.formatting import format_candidate_recipes, format_meal_plan
from app.planner.service import MealPlannerService
from app.recipes.weekly_discovery import WeeklyRecipeDiscoveryService

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
    if settings.recipe_discovery_enabled:
        discovery_hour, discovery_minute = settings.recipe_discovery_time.split(":", maxsplit=1)
        scheduler.add_job(
            weekly_recipe_discovery_job,
            trigger=CronTrigger(
                day_of_week=DAY_ALIASES.get(settings.recipe_discovery_day.casefold(), settings.recipe_discovery_day[:3]),
                hour=int(discovery_hour),
                minute=int(discovery_minute),
                timezone=settings.timezone,
            ),
            id="weekly_recipe_discovery",
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


async def weekly_recipe_discovery_job(settings_values: dict) -> None:
    settings = Settings.model_validate(settings_values)
    logger.info("weekly_recipe_discovery_started")
    with SessionLocal() as db:
        try:
            candidates = await WeeklyRecipeDiscoveryService(db, settings).discover_candidates()
        except Exception:
            logger.exception("weekly_recipe_discovery_failed")
            if _CURRENT_BOT and settings.admin_telegram_user_id:
                await _CURRENT_BOT.send_message(
                    chat_id=settings.admin_telegram_user_id,
                    text="Yeni tarif keşfi sırasında bir hata oldu. Bot çalışmaya devam ediyor; loglara bakmak gerekebilir.",
                )
            return
        if _CURRENT_BOT and settings.admin_telegram_user_id and candidates:
            await _CURRENT_BOT.send_message(
                chat_id=settings.admin_telegram_user_id,
                text=(
                    "🧪 Bu hafta yeni tarif adayları buldum. Bunlar menülere otomatik girmez; "
                    "beğendiklerini `/approverecipe Tarif Adı` ile onaylayabilirsin.\n\n"
                    f"{format_candidate_recipes(candidates)}"
                ),
                parse_mode="Markdown",
            )
            logger.info("weekly_recipe_discovery_sent candidates=%s", len(candidates))
