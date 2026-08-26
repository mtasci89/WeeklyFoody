from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.intents import NaturalLanguageRouter
from app.bot.keyboards import approval_keyboard
from app.bot.security import TelegramSecurity
from app.config import Settings
from app.db.models import PantryItem, PreferenceType, SessionState, WeeklyPlanningSession
from app.db.session import SessionLocal
from app.formatting import format_meal_plan, format_recipe_detail
from app.llm.base import Intent
from app.memory.preferences import PreferenceService
from app.planner.dates import next_week_start
from app.planner.revision import RevisionService
from app.planner.service import MealPlannerService
from app.recipes.service import RecipeService, normalize_name
from app.shopping.service import ShoppingListService
from app.workflow import WeeklyWorkflowService

logger = logging.getLogger(__name__)


class _TelegramBotNotifier:
    def __init__(self, bot):
        self.bot = bot

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text, **kwargs)


class TelegramHandlers:
    def __init__(self, settings: Settings, bot):
        self.settings = settings
        self.security = TelegramSecurity(settings)
        self.router = NaturalLanguageRouter(settings)
        self.notifier = _TelegramBotNotifier(bot)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("Merhaba. Haftalık yemek planı ajanı hazırım. /help yazabilirsin.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "/menu /approve /regenerate /recipes /recipe <ad> /addrecipe /deleterecipe <ad>\n"
            "/preferences /addpreference <kural> /deletepreference <kural>\n"
            "/shopping /history /pantry /pantryadd <malzeme> /pantryremove <malzeme>"
        )

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Menü komutunu yalnızca admin kullanabilir. Final menü onaylanınca alıcılara otomatik gönderilir.")
            return
        with SessionLocal() as db:
            session = MealPlannerService(db, self.settings).current_session()
            await update.effective_message.reply_text(format_meal_plan(session) if session else "Bu hafta için menü yok.", parse_mode="Markdown")

    async def approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            service = MealPlannerService(db, self.settings)
            session = service.current_session()
            if not session:
                await update.effective_message.reply_text("Onaylanacak aktif menü yok.")
                return
            service.approve(session)
            await WeeklyWorkflowService(db, self.settings, self.notifier).publish_final(session)
            await update.effective_message.reply_text("Menü onaylandı ve alıcılara gönderildi.")

    async def regenerate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            session = await MealPlannerService(db, self.settings).create_or_get_weekly_session(regenerate=True)
            await update.effective_message.reply_text(format_meal_plan(session), parse_mode="Markdown", reply_markup=approval_keyboard())

    async def recipes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            recipes = RecipeService(db).list_recipes(include_candidates=True)
            text = "\n".join(f"- {r.name} ({r.status.value})" for r in recipes) or "Tarif yok."
            await update.effective_message.reply_text(text)

    async def recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        name = " ".join(context.args)
        with SessionLocal() as db:
            recipe = RecipeService(db).find_recipe(name) if name else None
            await update.effective_message.reply_text(format_recipe_detail(recipe) if recipe else "Tarif bulunamadı.", parse_mode="Markdown")

    async def add_recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        text = update.effective_message.text or ""
        with SessionLocal() as db:
            recipe = RecipeService(db).add_recipe_from_text(text)
            logger.info("recipe_added recipe_id=%s", recipe.id)
            await update.effective_message.reply_text(f"{recipe.name} tarifini tarif kütüphanesine ekledim.")

    async def delete_recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        name = " ".join(context.args)
        with SessionLocal() as db:
            ok = RecipeService(db).disable_recipe(name)
            await update.effective_message.reply_text("Tarif pasifleştirildi." if ok else "Tarif bulunamadı.")

    async def preferences(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            prefs = PreferenceService(db).active()
            await update.effective_message.reply_text("\n".join(f"- {p.type.value}: {p.rule}" for p in prefs) or "Kayıtlı tercih yok.")

    async def add_preference(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        rule = " ".join(context.args) or (update.effective_message.text or "").replace("/addpreference", "").strip()
        with SessionLocal() as db:
            PreferenceService(db).add(rule, PreferenceType.HARD, source="telegram")
            logger.info("preference_added")
            await update.effective_message.reply_text("Kalıcı tercih kaydedildi.")

    async def delete_preference(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        query = " ".join(context.args)
        with SessionLocal() as db:
            ok = PreferenceService(db).delete(query)
            await update.effective_message.reply_text("Tercih silindi." if ok else "Tercih bulunamadı.")

    async def history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            sessions = db.scalars(
                select(WeeklyPlanningSession)
                .where(WeeklyPlanningSession.state.in_([SessionState.APPROVED, SessionState.PUBLISHED]))
                .order_by(WeeklyPlanningSession.week_start.desc())
                .limit(4)
            )
            text = "\n\n".join(format_meal_plan(s, final=True) for s in sessions) or "Geçmiş menü yok."
            await update.effective_message.reply_text(text, parse_mode="Markdown")

    async def shopping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            session = MealPlannerService(db, self.settings).current_session()
            if not session or not session.meal_plan or session.state not in (SessionState.APPROVED, SessionState.PUBLISHED):
                await update.effective_message.reply_text("Alışveriş listesi için önce menü onaylanmalı.")
                return
            service = ShoppingListService(db, self.settings)
            await update.effective_message.reply_text(service.format(service.generate(session.meal_plan)), parse_mode="Markdown")

    async def pantry(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            items = db.scalars(select(PantryItem).order_by(PantryItem.ingredient_name)).all()
            await update.effective_message.reply_text("\n".join(f"- {i.ingredient_name}" for i in items) or "Pantry boş.")

    async def pantry_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        item = normalize_name(" ".join(context.args))
        with SessionLocal() as db:
            if item:
                exists = db.scalar(select(PantryItem).where(PantryItem.ingredient_name == item))
                if not exists:
                    db.add(PantryItem(ingredient_name=item))
                    db.commit()
            await update.effective_message.reply_text("Pantry güncellendi.")

    async def pantry_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        item = normalize_name(" ".join(context.args))
        with SessionLocal() as db:
            existing = db.scalar(select(PantryItem).where(PantryItem.ingredient_name == item))
            if existing:
                db.delete(existing)
                db.commit()
            await update.effective_message.reply_text("Pantry güncellendi.")

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return
        await query.answer()
        if query.data == "approve":
            await self.approve(update, context)
        elif query.data == "regenerate":
            await self.regenerate(update, context)
        else:
            await query.message.reply_text("Değişiklik isteğini doğal dille yazabilirsin. Örn: Salı balık olmasın.")

    async def text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_user:
            return
        if not self.security.require_admin(update.effective_user.id):
            await update.effective_message.reply_text("Bu botta değişiklik yapma yetkisi sadece adminde.")
            return
        message = update.effective_message.text or ""
        routed = await self.router.route(message)
        with SessionLocal() as db:
            if routed.intent == Intent.APPROVE_PLAN:
                session = MealPlannerService(db, self.settings).current_session()
                if session:
                    MealPlannerService(db, self.settings).approve(session)
                    await WeeklyWorkflowService(db, self.settings, self.notifier).publish_final(session)
                    await update.effective_message.reply_text("Menüyü onayladım ve yayınladım.")
                return
            if routed.intent == Intent.ADD_RECIPE:
                recipe = RecipeService(db).add_recipe_from_text(routed.recipe_text or message)
                await update.effective_message.reply_text(f"{recipe.name} tarifini tarif kütüphanesine ekledim.")
                return
            if routed.intent == Intent.ADD_PREFERENCE and routed.preference:
                PreferenceService(db).add(routed.preference.rule, PreferenceType(routed.preference.type), source="telegram")
                await update.effective_message.reply_text("Kalıcı tercihi kaydettim.")
                return
            if routed.intent == Intent.ADD_PANTRY_ITEM and routed.pantry_item:
                item = normalize_name(routed.pantry_item)
                if not db.scalar(select(PantryItem).where(PantryItem.ingredient_name == item)):
                    db.add(PantryItem(ingredient_name=item))
                    db.commit()
                await update.effective_message.reply_text("Pantry güncellendi.")
                return
            if routed.intent == Intent.REGENERATE_PLAN:
                session = await MealPlannerService(db, self.settings).create_or_get_weekly_session(regenerate=True)
                await update.effective_message.reply_text(format_meal_plan(session), parse_mode="Markdown", reply_markup=approval_keyboard())
                return
            if routed.intent == Intent.SHOW_SHOPPING_LIST:
                await self.shopping(update, context)
                return
            if routed.intent == Intent.SHOW_MENU:
                await self.menu(update, context)
                return
            if routed.intent == Intent.MODIFY_PLAN:
                session = MealPlannerService(db, self.settings).current_session()
                if not session:
                    await update.effective_message.reply_text("Aktif taslak yok. /regenerate ile yeni taslak oluşturabilirsin.")
                    return
                revised = await RevisionService(db, self.settings).revise(session, message)
                await update.effective_message.reply_text(format_meal_plan(revised), parse_mode="Markdown", reply_markup=approval_keyboard())
                return
        await update.effective_message.reply_text("Bunu nasıl uygulayacağımdan emin olamadım. Biraz daha açık yazar mısın?")
