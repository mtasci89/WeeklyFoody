from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.intents import NaturalLanguageRouter
from app.bot.keyboards import approval_keyboard, home_keyboard
from app.bot.messages import reply
from app.bot.security import TelegramSecurity
from app.config import Settings
from app.db.models import PantryItem, PreferenceType, SessionState, WeeklyPlanningSession
from app.db.session import SessionLocal
from app.formatting import format_candidate_recipes, format_meal_plan, format_recipe_detail
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
        await reply(update.effective_message, "Merhaba! Menü, tarif ve alışveriş işlerini buradan yönetebiliriz.\n\nMenüyü görmek için 🍽 Menü’ye dokun. Onaylı menüyü de değiştirebilirsin: “Salı balık yerine Kuru Fasulye koy.”\n\nDeğişiklikler tekrar onayladığında alıcılara gönderilir.", reply_markup=home_keyboard())

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update.effective_message,
            "Menüdeki bir yemeği veya kişi sayısını değiştirmek için yaz:\n• Salı balığı çıkar.\n• Çarşamba Kuru Fasulye koy.\n• Cumartesi 6 kişi olacağız.\n\nOnaylı menü de düzenlenebilir. Değişiklikleri inceleyip tekrar onayla.\nBir isteği iptal etmek için “iptal” yaz.\n\n/menu /approve /regenerate /recipes /recipe <ad> /addrecipe /deleterecipe <ad>\n"
            "/discover <istek> /candidates /approverecipe <ad>\n"
            "/preferences /addpreference <kural> /deletepreference <kural>\n"
            "/shopping /history /pantry /pantryadd <malzeme> /pantryremove <malzeme>"
        )

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Menü komutunu yalnızca admin kullanabilir. Final menü onaylanınca alıcılara otomatik gönderilir.")
            return
        with SessionLocal() as db:
            session = self._active_session(db, context)
            if session:
                context.user_data["selected_session_id"] = session.id
            await reply(update.effective_message, format_meal_plan(session) if session else "Henüz menü yok. /regenerate ile oluşturabilirsin.", reply_markup=approval_keyboard(session) if session else home_keyboard())

    async def approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            service = MealPlannerService(db, self.settings)
            session = self._active_session(db, context)
            if not session:
                await reply(update.effective_message, "Onaylanacak aktif menü yok.")
                return
            service.approve(session)
            sent = await WeeklyWorkflowService(db, self.settings, self.notifier).publish_final(session)
            await reply(update.effective_message, "Menü onaylandı; güncel menü ve alışveriş listesi gönderildi." if sent else "Bu sürüm zaten gönderildi.", reply_markup=approval_keyboard(session))

    async def regenerate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            current = self._active_session(db, context)
            session = await MealPlannerService(db, self.settings).create_or_get_weekly_session(week_start=current.week_start if current else None, regenerate=True)
            context.user_data["selected_session_id"] = session.id
            await reply(update.effective_message, format_meal_plan(session), parse_mode="Markdown", reply_markup=approval_keyboard(session))

    async def recipes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            recipes = RecipeService(db).list_recipes(include_candidates=True)
            text = "\n".join(f"- {r.name} ({r.status.value})" for r in recipes) or "Tarif yok."
            await reply(update.effective_message, text)

    async def recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        name = " ".join(context.args)
        with SessionLocal() as db:
            recipe = RecipeService(db).find_recipe(name) if name else None
            await reply(update.effective_message, format_recipe_detail(recipe) if recipe else "Tarif bulunamadı.", parse_mode="Markdown")

    async def add_recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        text = update.effective_message.text or ""
        if not _has_recipe_details(text):
            context.user_data["awaiting_recipe_text"] = True
            await reply(update.effective_message,
                "Tabii. Tarifin adını ve malzemelerini yazıp gönder. Örn:\n\n"
                "Tavuk Fajita\n600 gr tavuk\n2 biber\n1 soğan\nBaharatlarla sotele."
            )
            return
        with SessionLocal() as db:
            recipe = RecipeService(db).add_recipe_from_text(text)
            logger.info("recipe_added recipe_id=%s", recipe.id)
            await reply(update.effective_message, f"{recipe.name} tarifini tarif kütüphanesine ekledim.")

    async def delete_recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        name = " ".join(context.args)
        with SessionLocal() as db:
            ok = RecipeService(db).disable_recipe(name)
            await reply(update.effective_message, "Tarif pasifleştirildi." if ok else "Tarif bulunamadı.")

    async def discover(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        query = " ".join(context.args).strip()
        if not query:
            await reply(update.effective_message, "Ne tür tarif bulayım? Örn: `/discover pratik tavuk yemeği`", parse_mode="Markdown")
            return
        await reply(update.effective_message, "Yeni tarif adayları arıyorum; birkaç saniye sürebilir.")
        with SessionLocal() as db:
            recipes = await RecipeService(db).discover_recipes(query, self.settings, limit=3)
            await reply(update.effective_message, format_candidate_recipes(recipes), parse_mode="Markdown")

    async def candidates(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            await reply(update.effective_message, format_candidate_recipes(RecipeService(db).list_candidates()), parse_mode="Markdown")

    async def approve_recipe_candidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        name = " ".join(context.args).strip()
        if not name:
            await reply(update.effective_message, "Hangi adayı onaylayayım? Örn: `/approverecipe Tavuk Fajita`", parse_mode="Markdown")
            return
        with SessionLocal() as db:
            ok = RecipeService(db).approve_candidate(name)
            await reply(update.effective_message, "Tarifi kalıcı kütüphaneye ekledim." if ok else "Bu isimde aday tarif bulamadım.")

    async def preferences(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            prefs = PreferenceService(db).active()
            await reply(update.effective_message, "\n".join(f"- {p.type.value}: {p.rule}" for p in prefs) or "Kayıtlı tercih yok.")

    async def add_preference(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        rule = " ".join(context.args) or (update.effective_message.text or "").replace("/addpreference", "").strip()
        with SessionLocal() as db:
            PreferenceService(db).add(rule, PreferenceType.HARD, source="telegram")
            logger.info("preference_added")
            await reply(update.effective_message, "Kalıcı tercih kaydedildi.")

    async def delete_preference(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        query = " ".join(context.args)
        with SessionLocal() as db:
            ok = PreferenceService(db).delete(query)
            await reply(update.effective_message, "Tercih silindi." if ok else "Tercih bulunamadı.")

    async def history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            sessions = db.scalars(
                select(WeeklyPlanningSession)
                .where(WeeklyPlanningSession.state.in_([SessionState.APPROVED, SessionState.PUBLISHED]))
                .order_by(WeeklyPlanningSession.week_start.desc())
                .limit(4)
            )
            text = "\n\n".join(format_meal_plan(s, final=True) for s in sessions) or "Geçmiş menü yok."
            await reply(update.effective_message, text, parse_mode="Markdown")

    async def shopping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            session = self._active_session(db, context)
            if not session or not session.meal_plan or session.state not in (SessionState.APPROVED, SessionState.PUBLISHED):
                await reply(update.effective_message, "Alışveriş listesi için önce menü onaylanmalı.")
                return
            service = ShoppingListService(db, self.settings)
            await reply(update.effective_message, service.format(service.generate(session.meal_plan)), parse_mode="Markdown")

    async def pantry(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            items = db.scalars(select(PantryItem).order_by(PantryItem.ingredient_name)).all()
            await reply(update.effective_message, "\n".join(f"- {i.ingredient_name}" for i in items) or "Pantry boş.")

    async def pantry_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        item = normalize_name(" ".join(context.args))
        with SessionLocal() as db:
            if item:
                exists = db.scalar(select(PantryItem).where(PantryItem.ingredient_name == item))
                if not exists:
                    db.add(PantryItem(ingredient_name=item))
                    db.commit()
            await reply(update.effective_message, "Pantry güncellendi.")

    async def pantry_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await reply(update.effective_message, "Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        item = normalize_name(" ".join(context.args))
        with SessionLocal() as db:
            existing = db.scalar(select(PantryItem).where(PantryItem.ingredient_name == item))
            if existing:
                db.delete(existing)
                db.commit()
            await reply(update.effective_message, "Pantry güncellendi.")

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await query.answer("Bu işlem yalnızca admin için.", show_alert=True)
            return
        await query.answer()
        parts = (query.data or "").split(":")
        if len(parts) != 3:
            await reply(query.message, "Bu buton eski bir menüye ait. /menu ile güncel menüyü aç.")
            return
        action, session_id, version = parts
        with SessionLocal() as db:
            session = db.get(WeeklyPlanningSession, session_id)
            if not session or str(session.draft_version) != version:
                await reply(query.message, "Menü değişmiş. /menu ile son sürümü açıp yeniden dene.")
                return
            context.user_data["selected_session_id"] = session.id
        if action == "approve":
            await self.approve(update, context)
        elif action == "regenerate":
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            await reply(query.message, "Bu haftanın tüm yemeklerini yeniden hazırlayayım mı? Yalnızca bir yemeği değiştirmek istersen doğrudan yazabilirsin.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Evet, baştan hazırla", callback_data=f"regen_yes:{session_id}:{version}")]]))
        elif action == "regen_yes":
            await self.regenerate(update, context)
        elif action == "change_help":
            context.user_data["editing_plan"] = True
            await reply(query.message, "Neyi değiştirelim?\n\n• Salı balığı çıkar.\n• Çarşamba Kuru Fasulye koy.\n• Cumartesi 6 kişi olacağız.\n\nOnaylı menüde yaptığın değişiklikler de önce taslak olarak gösterilir.")

    async def text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_user:
            return
        if not self.security.require_admin(update.effective_user.id):
            await reply(update.effective_message, "Bu botta değişiklik yapma yetkisi sadece adminde.")
            return
        message = update.effective_message.text or ""
        shortcuts = {"🍽 Menü": self.menu, "🛒 Alışveriş": self.shopping, "📚 Tarifler": self.recipes, "🧪 Aday tarifler": self.candidates, "⚙️ Tercihler": self.preferences, "❓ Yardım": self.help}
        if message in shortcuts:
            await shortcuts[message](update, context)
            return
        with SessionLocal() as db:
            session = self._active_session(db, context, message)
            if message.casefold().strip() in {"iptal", "vazgeç", "vazgec"}:
                context.user_data.pop("awaiting_recipe_text", None)
                context.user_data.pop("editing_plan", None)
                if session:
                    session.context = {k: v for k, v in (session.context or {}).items() if k not in {"pending_revision", "clarification"}}
                    db.commit()
                await reply(update.effective_message, "Tamam, bekleyen isteği iptal ettim. Menü aynı kaldı.", reply_markup=home_keyboard())
                return
            if context.user_data.get("awaiting_recipe_text"):
                if message.casefold().strip() in {"iptal", "vazgeç", "vazgec"}:
                    context.user_data.pop("awaiting_recipe_text", None)
                    await reply(update.effective_message, "Tamam, tarif eklemeyi iptal ettim.")
                    return
                if not _has_recipe_details(message):
                    await reply(update.effective_message,
                        "Bunu tarif olarak kaydetmem için en az tarif adı ve bir malzeme satırı lazım. "
                        "Örn:\n\nTavuk Fajita\n600 gr tavuk\n2 biber"
                    )
                    return
                recipe = RecipeService(db).add_recipe_from_text(message)
                context.user_data.pop("awaiting_recipe_text", None)
                logger.info("recipe_added recipe_id=%s", recipe.id)
                await reply(update.effective_message, f"{recipe.name} tarifini tarif kütüphanesine ekledim.")
                return

            router_context = self._router_context(db)
            pending = session and (session.context or {}).get("pending_revision")
            routed = await self.router.route(message, router_context)
            if routed.clarification_question:
                await reply(update.effective_message, routed.clarification_question)
                return
            if pending and routed.intent in {Intent.UNKNOWN, Intent.GENERAL_QUESTION}:
                from app.llm.base import IntentOutput
                routed = IntentOutput(intent=Intent.MODIFY_PLAN)
            if routed.intent == Intent.APPROVE_PLAN:
                session = self._active_session(db, context)
                if session:
                    MealPlannerService(db, self.settings).approve(session)
                    sent = await WeeklyWorkflowService(db, self.settings, self.notifier).publish_final(session)
                    await reply(update.effective_message, "Menüyü onayladım ve gönderdim." if sent else "Bu sürüm zaten gönderildi.", reply_markup=approval_keyboard(session))
                else:
                    await reply(update.effective_message, "Onaylanacak aktif menü yok.")
                return
            if routed.intent == Intent.ADD_RECIPE:
                recipe_text = routed.recipe_text or message
                if not _has_recipe_details(recipe_text):
                    context.user_data["awaiting_recipe_text"] = True
                    await reply(update.effective_message,
                        "Tabii. Eklemek istediğin tarifi adı ve malzemeleriyle gönder. "
                        "Instagram/link varsa aynı mesaja koyabilirsin.\n\n"
                        "Örn:\nTavuk Fajita\n600 gr tavuk\n2 biber\n1 soğan"
                    )
                    return
                recipe = RecipeService(db).add_recipe_from_text(recipe_text)
                context.user_data.pop("awaiting_recipe_text", None)
                await reply(update.effective_message, f"{recipe.name} tarifini tarif kütüphanesine ekledim.")
                return
            if routed.intent == Intent.DISCOVER_RECIPE:
                await reply(update.effective_message, "Yeni tarif adayları arıyorum; birkaç saniye sürebilir.")
                recipes = await RecipeService(db).discover_recipes(routed.discovery_query or message, self.settings, limit=3)
                await reply(update.effective_message, format_candidate_recipes(recipes), parse_mode="Markdown")
                return
            if routed.intent == Intent.SHOW_RECIPE_CANDIDATES:
                await reply(update.effective_message, format_candidate_recipes(RecipeService(db).list_candidates()), parse_mode="Markdown")
                return
            if routed.intent == Intent.APPROVE_RECIPE_CANDIDATE:
                name = routed.recipe_name or message.replace("bu tarifi tariflerime ekle", "").strip()
                ok = RecipeService(db).approve_candidate(name)
                await reply(update.effective_message, "Tarifi kalıcı kütüphaneye ekledim." if ok else "Bu isimde aday tarif bulamadım.")
                return
            if routed.intent == Intent.ADD_PREFERENCE and routed.preference:
                PreferenceService(db).add(routed.preference.rule, PreferenceType(routed.preference.type), source="telegram")
                await reply(update.effective_message, "Kalıcı tercihi kaydettim.")
                return
            if routed.intent == Intent.ADD_PANTRY_ITEM and routed.pantry_item:
                item = normalize_name(routed.pantry_item)
                if not db.scalar(select(PantryItem).where(PantryItem.ingredient_name == item)):
                    db.add(PantryItem(ingredient_name=item))
                    db.commit()
                await reply(update.effective_message, "Pantry güncellendi.")
                return
            if routed.intent == Intent.REGENERATE_PLAN:
                current = self._active_session(db, context, message)
                session = await MealPlannerService(db, self.settings).create_or_get_weekly_session(week_start=current.week_start if current else None, regenerate=True)
                context.user_data["selected_session_id"] = session.id
                await reply(update.effective_message, format_meal_plan(session), parse_mode="Markdown", reply_markup=approval_keyboard(session))
                return
            if routed.intent == Intent.SHOW_SHOPPING_LIST:
                await self.shopping(update, context)
                return
            if routed.intent == Intent.SHOW_MENU:
                await self.menu(update, context)
                return
            if routed.intent == Intent.SHOW_RECIPE:
                recipe = RecipeService(db).find_recipe(routed.recipe_name or message)
                await reply(update.effective_message, format_recipe_detail(recipe) if recipe else "Tarif bulunamadı.", parse_mode="Markdown")
                return
            if routed.intent == Intent.MODIFY_PLAN:
                session = self._active_session(db, context, message)
                if not session:
                    await reply(update.effective_message, "Aktif taslak yok. /regenerate ile yeni taslak oluşturabilirsin.")
                    return
                revised = await RevisionService(db, self.settings).revise(session, message)
                context.user_data["selected_session_id"] = revised.id
                question = (revised.context or {}).get("clarification")
                await reply(update.effective_message, question or ("Değişiklikleri taslağa kaydettim. İnceledikten sonra onaylayıp gönderebilirsin.\n\n" + format_meal_plan(revised)), reply_markup=approval_keyboard(revised))
                return
            if routed.intent == Intent.SHOW_PREFERENCES:
                await self.preferences(update, context)
                return
            if routed.intent in {Intent.GENERAL_QUESTION, Intent.UNKNOWN}:
                answer = await self.router.answer_general_question(message, router_context)
                await reply(update.effective_message, answer)
                return

    def _active_session(self, db, context, message=""):
        service = MealPlannerService(db, self.settings)
        if any(w in message.casefold() for w in ("bu hafta", "gelecek hafta", "önümüzdeki hafta")):
            return service.session_for_message(message)
        selected_id = context.user_data.get("selected_session_id")
        selected = db.get(WeeklyPlanningSession, selected_id) if selected_id else None
        return selected or service.current_session()

    def _router_context(self, db) -> dict:
        session = MealPlannerService(db, self.settings).current_session()
        return {
            "bot_role": "personal_family_weekly_meal_planner",
            "language": "tr",
            "can_modify_plan": bool(session),
            "has_active_plan": bool(session),
            "session_state": session.state.value if session else None,
            "week_start": session.week_start.isoformat() if session else None,
            "commands": [
                "/menu",
                "/regenerate",
                "/approve",
                "/addrecipe",
                "/discover",
                "/recipes",
                "/shopping",
                "/preferences",
                "/pantry",
            ],
        }


def _has_recipe_details(text: str) -> bool:
    cleaned = text.replace("/addrecipe", "").replace("Bu tarifi kaydet:", "").replace("bu tarifi kaydet:", "").strip()
    lines = [line.strip(" -\t") for line in cleaned.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    units = {"gr", "g", "gram", "kg", "ml", "l", "lt", "adet", "paket", "demet", "kaşığı", "bardak"}
    for line in lines[1:]:
        words = set(line.casefold().split())
        if any(char.isdigit() for char in line) or words.intersection(units):
            return True
    return False

