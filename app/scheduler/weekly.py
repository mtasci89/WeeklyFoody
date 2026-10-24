from __future__ import annotations

import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot.keyboards import approval_keyboard
from app.config import Settings, get_settings
from app.db.session import SessionLocal, build_engine
from app.formatting import format_candidate_recipes, format_meal_plan, split_for_telegram
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
    # Jobstore uygulamanin motorunu paylasir. Ham `url=` vermek
    # `postgresql://` on-ekini psycopg2'ye cozdurur ve psycopg v3 kurulu
    # oldugu icin acilista ModuleNotFoundError atar (RUN-01).
    jobstores = {"default": SQLAlchemyJobStore(engine=build_engine(settings))}
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
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
    return scheduler


async def _notify_admin(settings: Settings, text: str) -> None:
    """Admin'e en iyi caba ile haber verir; bildirim hatasi isi dusurmez."""
    if not (_CURRENT_BOT and settings.admin_telegram_user_id):
        return
    try:
        await _CURRENT_BOT.send_message(chat_id=settings.admin_telegram_user_id, text=text)
    except Exception:
        logger.exception("admin_notify_failed")


async def weekly_plan_job(**_legacy: object) -> None:
    """Haftalik taslagi uretir ve admin'e gonderir.

    `_legacy` yalnizca eski surumden kalmis, kwargs tasiyan kalici job
    kayitlarini tolere etmek icin var; yeni kayitlar argumansiz.
    """
    settings = get_settings()
    logger.info("weekly_plan_started")
    try:
        with SessionLocal() as db:
            from app.agent.nutrition import fill_for_rules
            from app.recipes.service import RecipeService

            await fill_for_rules(db, settings, RecipeService(db).list_recipes(), library=True)
            session = await MealPlannerService(db, settings).create_or_get_weekly_session()
            if await _agent_new_dishes(settings, session):
                db.expire_all()
                session = MealPlannerService(db, settings).current_session(session.week_start)
            if session.meal_plan:
                await fill_for_rules(db, settings, [i.recipe for i in session.meal_plan.items])
            if _CURRENT_BOT and settings.admin_telegram_user_id and settings.telegram_menu_messages:
                text = f"🍽️ Önümüzdeki haftanın yemek planını hazırladım.\n\n{format_meal_plan(session)}"
                chunks = split_for_telegram(text)
                for index, chunk in enumerate(chunks):
                    await _CURRENT_BOT.send_message(
                        chat_id=settings.admin_telegram_user_id, text=chunk, parse_mode="Markdown",
                        reply_markup=approval_keyboard() if index == len(chunks) - 1 else None,
                    )
                logger.info("draft_sent_to_admin session_id=%s", session.id)
    except Exception as error:
        # Sessizce olmek yok: yoksa admin pazar sabahi hicbir sey gormuyor
        # ve nedenini anlamak icin loglara bakmasi gerekiyor (RUN-02).
        logger.exception("weekly_plan_failed")
        from app.memory.rules import RuleViolation
        detail = str(error) if isinstance(error, RuleViolation) else "Bu haftanın menüsünü hazırlarken bir hata oldu ve taslak oluşmadı."
        await _notify_admin(settings, detail + " /preferences ile kuralları kontrol edip /regenerate ile tekrar deneyebilirsin.")


async def _agent_new_dishes(settings: Settings, session) -> bool:
    """Taslakta hedeflenen kadar yeni yemek yoksa (cumartesi keşfi aday
    bulamadıysa) ajan internete bakıp ekler. Hata taslağı bozmaz."""
    from app.agent.runner import MealPlannerAgent
    from app.memory.rules import MealRules
    from app.planner.novelty import is_new

    if not session.meal_plan or not MealPlannerAgent.available(settings):
        return False
    with SessionLocal() as db:
        target = MealRules.from_db(db).new_dish_target(settings)
    missing = target - sum(1 for item in session.meal_plan.items if is_new(item.recipe))
    if missing <= 0:
        return False
    from app.agent.prompts import weekly_novelty_prompt

    agent = MealPlannerAgent(settings, SessionLocal)
    try:
        reply = await agent.reply(settings.admin_telegram_user_id, weekly_novelty_prompt(session.week_start, missing))
        logger.info("weekly_new_dishes_agent ok=%s", reply.ok)
        return True
    except Exception:
        logger.exception("weekly_new_dishes_agent_failed")
        return False
    finally:
        await agent.aclose()


async def weekly_recipe_discovery_job(**_legacy: object) -> None:
    settings = get_settings()
    logger.info("weekly_recipe_discovery_started")
    if not settings.recipe_discovery_enabled:
        return
    from app.agent.runner import MealPlannerAgent

    if MealPlannerAgent.available(settings):
        await _agent_discovery(settings)
        return
    with SessionLocal() as db:
        try:
            candidates = await WeeklyRecipeDiscoveryService(db, settings).discover_candidates()
        except Exception:
            logger.exception("weekly_recipe_discovery_failed")
            await _notify_admin(
                settings,
                "Yeni tarif keşfi sırasında bir hata oldu. Bot çalışmaya devam ediyor; "
                "loglara bakmak gerekebilir.",
            )
            return
        if _CURRENT_BOT and settings.admin_telegram_user_id and candidates and settings.telegram_menu_messages:
            await _CURRENT_BOT.send_message(
                chat_id=settings.admin_telegram_user_id,
                text=(
                    "🧪 Bu hafta yeni tarif adayları buldum. Bazıları haftalık menüye \"yeni\" olarak "
                    "girecek; beğendiklerini `/approverecipe Tarif Adı` ile kalıcı listeye alabilirsin.\n\n"
                    f"{format_candidate_recipes(candidates)}"
                ),
                parse_mode="Markdown",
            )
            logger.info("weekly_recipe_discovery_sent candidates=%s", len(candidates))


async def _agent_discovery(settings: Settings) -> None:
    """Haftalik kesfi ajan yapar: her kategori icin ayri bir turda web'de arar
    ve bulduklarini aday kaydeder. Sonuclar yoneticinin sohbetine gider; yonetici
    "ikincisini onayla" diye cevap verebilsin diye ayni sohbet gecmisi kullanilir."""
    from app.agent.prompts import discovery_prompt
    from app.agent.runner import MealPlannerAgent

    admin = settings.admin_telegram_user_id
    agent = MealPlannerAgent(settings, SessionLocal)
    replies: list[str] = []
    try:
        for query in settings.recipe_discovery_queries:
            reply = await agent.reply(admin, discovery_prompt(query, settings.recipe_discovery_limit_per_category))
            replies.append(reply.text)
            if not reply.ok:
                logger.warning("weekly_recipe_discovery_turn_failed query=%s", query[:60])
    finally:
        await agent.aclose()
    logger.info("weekly_recipe_discovery_completed turns=%s", len(replies))
    if _CURRENT_BOT and admin and settings.telegram_menu_messages:
        text = (
            "🧪 Haftalık tarif keşfi: internette yeni tarifler aradım. Bulduklarım aday "
            "olarak bekliyor; bazıları yarınki menüye \"yeni\" olarak girecek. /candidates ile "
            "hepsini görebilir, beğendiğin için \"şunu onayla\" diye yazabilirsin.\n\n" + "\n\n".join(replies)
        )
        for chunk in split_for_telegram(text):
            await _CURRENT_BOT.send_message(chat_id=admin, text=chunk)
