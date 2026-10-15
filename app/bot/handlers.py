from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.agent.runner import MealPlannerAgent
from app.bot.intents import NaturalLanguageRouter
from app.bot.keyboards import approval_keyboard
from app.bot.security import TelegramSecurity
from app.config import Settings
from app.db.models import PantryItem, PreferenceType, SessionState, WeeklyPlanningSession
from app.db.session import SessionLocal
from app.formatting import (
    format_candidate_recipes,
    format_meal_plan,
    format_recipe_detail,
    split_for_telegram,
)
from app.llm.base import Intent
from app.memory.preferences import PreferenceService
from app.memory.rules import MealRules, RuleViolation
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
        self.agent = MealPlannerAgent(settings, SessionLocal) if MealPlannerAgent.available(settings) else None
        if self.agent:
            logger.info("agent_enabled provider=%s model=%s", settings.agent_provider, self.agent.model)
        else:
            logger.info("agent_disabled reason=no_api_key_or_disabled fallback=intent_router")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("Merhaba. Haftalık yemek planı ajanı hazırım. /help yazabilirsin.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "/menu /approve /regenerate /recipes /recipe <ad> /addrecipe /deleterecipe <ad>\n"
            "/discover <istek> /candidates /approverecipe <ad>\n"
            "/kurallar /kural_ekle <kural> /kural_sil <no|ifade> /kurallari_yaz\n"
            "/preferences /addpreference <kural> /deletepreference <kural>\n"
            "/shopping /history /pantry /pantryadd <malzeme> /pantryremove <malzeme>"
        )

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Menü komutunu yalnızca admin kullanabilir. Final menü onaylanınca alıcılara otomatik gönderilir.")
            return
        with SessionLocal() as db:
            session = MealPlannerService(db, self.settings).current_session()
            await reply_menu(update.effective_message, format_meal_plan(session) if session else "Bu hafta için menü yok.")

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
            await reply_menu(update.effective_message, format_meal_plan(session), reply_markup=approval_keyboard())

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
        if not _has_recipe_details(text):
            context.user_data["awaiting_recipe_text"] = True
            await update.effective_message.reply_text(
                "Tabii. Tarifin adını ve malzemelerini yazıp gönder. Örn:\n\n"
                "Tavuk Fajita\n600 gr tavuk\n2 biber\n1 soğan\nBaharatlarla sotele."
            )
            return
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

    async def discover(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        query = " ".join(context.args).strip()
        if not query:
            await update.effective_message.reply_text("Ne tür tarif bulayım? Örn: `/discover pratik tavuk yemeği`", parse_mode="Markdown")
            return
        if self.agent is not None:
            from app.agent.prompts import discovery_prompt

            await update.effective_message.reply_text(
                "İnternette arıyorum; bulduklarımı aday olarak kaydedeceğim. Bir iki dakika sürebilir."
            )
            await self._agent_turn(update, discovery_prompt(query, limit=3))
            return
        await update.effective_message.reply_text("Yeni tarif adayları arıyorum; birkaç saniye sürebilir.")
        with SessionLocal() as db:
            recipes = await RecipeService(db).discover_recipes(query, self.settings, limit=3)
            await update.effective_message.reply_text(format_candidate_recipes(recipes), parse_mode="Markdown")

    async def candidates(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            await update.effective_message.reply_text(format_candidate_recipes(RecipeService(db).list_candidates()), parse_mode="Markdown")

    async def approve_recipe_candidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        name = " ".join(context.args).strip()
        if not name:
            await update.effective_message.reply_text("Hangi adayı onaylayayım? Örn: `/approverecipe Tavuk Fajita`", parse_mode="Markdown")
            return
        with SessionLocal() as db:
            ok = RecipeService(db).approve_candidate(name)
            await update.effective_message.reply_text("Tarifi kalıcı kütüphaneye ekledim." if ok else "Bu isimde aday tarif bulamadım.")

    async def preferences(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        with SessionLocal() as db:
            prefs = PreferenceService(db).active()
            text = "\n".join(f"- {p.type.value}: {p.rule}" for p in prefs) or "Kayıtlı tercih yok."
            text += "\n\n" + "\n".join(MealRules.from_db(db).summary())
            text += "\nKurallar paneldeki Yemek Kurallarım alanından düzenlenebilir. /addpreference <kural> ile ekleyebilir, /deletepreference <kural> ile silebilirsin."
            for chunk in split_for_telegram(text):
                await update.effective_message.reply_text(chunk)

    async def add_preference(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.security.require_admin(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
            return
        rule = " ".join(context.args) or (update.effective_message.text or "").replace("/addpreference", "").strip()
        with SessionLocal() as db:
            try:
                PreferenceService(db).add(rule, PreferenceType.HARD, source="telegram")
            except ValueError as error:
                await update.effective_message.reply_text(f"Kural kaydedilmedi: {error}")
                return
            logger.info("preference_added")
            for chunk in split_for_telegram("Kalıcı tercih kaydedildi.\n" + "\n".join(MealRules.from_db(db).summary())):
                await update.effective_message.reply_text(chunk)

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

    def _house_rules(self):
        from app.agent.rules import HouseRules

        return HouseRules(SessionLocal)

    async def _require_admin(self, update: Update) -> bool:
        if self.security.require_admin(update.effective_user.id if update.effective_user else None):
            return True
        await update.effective_message.reply_text("Bu komut yalnızca admin tarafından kullanılabilir.")
        return False

    async def rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._require_admin(update):
            return
        house = self._house_rules()
        for chunk in split_for_telegram(rules_text(house.active(), house.summary())):
            await update.effective_message.reply_text(chunk)

    async def rule_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._require_admin(update):
            return
        rule = command_body(update.effective_message.text)
        if not rule:
            await update.effective_message.reply_text("Kullanım: /kural_ekle Balık kullanma")
            return
        house = self._house_rules()
        added, detail = house.add(rule)
        logger.info("house_rule_added added=%s", added)
        if not added:
            await update.effective_message.reply_text(f"Kural eklenmedi: {detail}")
            return
        text = "Kural eklendi, bundan sonra her planlamada uygulanacak.\n\n" + "\n".join(house.summary())
        for chunk in split_for_telegram(text):
            await update.effective_message.reply_text(chunk)

    async def rule_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._require_admin(update):
            return
        house = self._house_rules()
        phrase = command_body(update.effective_message.text)
        active = house.active()
        if phrase.isdigit() and 1 <= int(phrase) <= len(active):
            matches = [active[int(phrase) - 1]]
        else:
            matches = house.matching(phrase) if phrase else []
        if not phrase:
            text = "Kullanım: /kural_sil 2 (numara /kurallar listesinden) ya da /kural_sil balık"
        elif not matches:
            text = f"'{phrase}' geçen bir kural yok. /kurallar ile listeye bakabilirsin."
        elif len(matches) > 1:
            listed = "\n".join(f"- {rule}" for rule in matches)
            text = f"Birden fazla kural eşleşti, numarasıyla sil:\n{listed}"
        else:
            house.remove(matches[0])
            logger.info("house_rule_deleted")
            text = f"Kural silindi: {matches[0]}"
        await update.effective_message.reply_text(text)

    async def rules_replace(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._require_admin(update):
            return
        body = command_body(update.effective_message.text)
        if not body:
            await update.effective_message.reply_text(
                "Tüm listeyi tek mesajda yeniden yazmak için komutun altına her satıra bir kural yaz:\n\n"
                "/kurallari_yaz\nBalık kullanma\nHer akşam 3 farklı yemek olsun\n\n"
                "Mevcut listenin yerine geçer. Hepsini silmek için: /kurallari_yaz sil"
            )
            return
        house = self._house_rules()
        try:
            rules = house.replace("" if body.casefold() == "sil" else body)
        except ValueError as error:
            await update.effective_message.reply_text(f"Kurallar kaydedilmedi, liste değişmedi: {error}")
            return
        logger.info("house_rules_replaced count=%s", len(rules))
        for chunk in split_for_telegram(rules_text(rules, house.summary())):
            await update.effective_message.reply_text(chunk)

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
        if self.agent and not context.user_data.get("awaiting_recipe_text"):
            await self._agent_turn(update, message)
            return
        with SessionLocal() as db:
            if context.user_data.get("awaiting_recipe_text"):
                if message.casefold().strip() in {"iptal", "vazgeç", "vazgec"}:
                    context.user_data.pop("awaiting_recipe_text", None)
                    await update.effective_message.reply_text("Tamam, tarif eklemeyi iptal ettim.")
                    return
                if not _has_recipe_details(message):
                    await update.effective_message.reply_text(
                        "Bunu tarif olarak kaydetmem için en az tarif adı ve bir malzeme satırı lazım. "
                        "Örn:\n\nTavuk Fajita\n600 gr tavuk\n2 biber"
                    )
                    return
                recipe = RecipeService(db).add_recipe_from_text(message)
                context.user_data.pop("awaiting_recipe_text", None)
                logger.info("recipe_added recipe_id=%s", recipe.id)
                await update.effective_message.reply_text(f"{recipe.name} tarifini tarif kütüphanesine ekledim.")
                return

            router_context = self._router_context(db)
            routed = await self.router.route(message, router_context)
            if routed.intent == Intent.APPROVE_PLAN:
                session = MealPlannerService(db, self.settings).current_session()
                if session:
                    MealPlannerService(db, self.settings).approve(session)
                    await WeeklyWorkflowService(db, self.settings, self.notifier).publish_final(session)
                    await update.effective_message.reply_text("Menüyü onayladım ve yayınladım.")
                else:
                    await update.effective_message.reply_text("Onaylanacak aktif menü yok.")
                return
            if routed.intent == Intent.ADD_RECIPE:
                recipe_text = routed.recipe_text or message
                if not _has_recipe_details(recipe_text):
                    context.user_data["awaiting_recipe_text"] = True
                    await update.effective_message.reply_text(
                        "Tabii. Eklemek istediğin tarifi adı ve malzemeleriyle gönder. "
                        "Instagram/link varsa aynı mesaja koyabilirsin.\n\n"
                        "Örn:\nTavuk Fajita\n600 gr tavuk\n2 biber\n1 soğan"
                    )
                    return
                recipe = RecipeService(db).add_recipe_from_text(recipe_text)
                context.user_data.pop("awaiting_recipe_text", None)
                await update.effective_message.reply_text(f"{recipe.name} tarifini tarif kütüphanesine ekledim.")
                return
            if routed.intent == Intent.DISCOVER_RECIPE:
                await update.effective_message.reply_text("Yeni tarif adayları arıyorum; birkaç saniye sürebilir.")
                recipes = await RecipeService(db).discover_recipes(routed.discovery_query or message, self.settings, limit=3)
                await update.effective_message.reply_text(format_candidate_recipes(recipes), parse_mode="Markdown")
                return
            if routed.intent == Intent.SHOW_RECIPE_CANDIDATES:
                await update.effective_message.reply_text(format_candidate_recipes(RecipeService(db).list_candidates()), parse_mode="Markdown")
                return
            if routed.intent == Intent.APPROVE_RECIPE_CANDIDATE:
                name = routed.recipe_name or message.replace("bu tarifi tariflerime ekle", "").strip()
                ok = RecipeService(db).approve_candidate(name)
                await update.effective_message.reply_text("Tarifi kalıcı kütüphaneye ekledim." if ok else "Bu isimde aday tarif bulamadım.")
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
                await reply_menu(update.effective_message, format_meal_plan(session), reply_markup=approval_keyboard())
                return
            if routed.intent == Intent.SHOW_SHOPPING_LIST:
                await self.shopping(update, context)
                return
            if routed.intent == Intent.SHOW_MENU:
                await self.menu(update, context)
                return
            if routed.intent == Intent.SHOW_RECIPE:
                recipe = RecipeService(db).find_recipe(routed.recipe_name or message)
                await update.effective_message.reply_text(format_recipe_detail(recipe) if recipe else "Tarif bulunamadı.", parse_mode="Markdown")
                return
            if routed.intent == Intent.MODIFY_PLAN:
                session = MealPlannerService(db, self.settings).current_session()
                if not session:
                    await update.effective_message.reply_text("Aktif taslak yok. /regenerate ile yeni taslak oluşturabilirsin.")
                    return
                revised = await RevisionService(db, self.settings).revise(session, message)
                await reply_menu(update.effective_message, format_meal_plan(revised), reply_markup=approval_keyboard())
                return
            if routed.intent in {Intent.GENERAL_QUESTION, Intent.UNKNOWN}:
                answer = await self.router.answer_general_question(message, router_context)
                await update.effective_message.reply_text(answer)
                return

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Yakalanmamis her handler istisnasi buraya duser.

        Eskiden hic hata yakalayici yoktu: python-telegram-bot istisnayi
        loglayip geciyor, kullanici tarafinda hicbir sey olmuyordu. Her
        arizanin sessiz arizaya donusmesinin sebebi buydu (RUN-03).
        """
        if isinstance(context.error, RuleViolation):
            message = getattr(update, "effective_message", None)
            if message is not None and self.security.require_admin(getattr(getattr(update, "effective_user", None), "id", None)):
                await message.reply_text(f"İşlem tamamlanmadı: {context.error}\nKuralları /preferences ile görebilirsin.")
            return
        logger.exception("handler_failed", exc_info=context.error)
        message = getattr(update, "effective_message", None)
        if message is not None:
            try:
                await message.reply_text(
                    "Bir aksilik oldu, isteğini tamamlayamadım. Tekrar dener misin? "
                    "Sorun sürerse /menu ve /shopping komutları çalışmaya devam ediyor."
                )
            except Exception:
                logger.exception("error_reply_failed")
        admin_id = self.settings.admin_telegram_user_id
        chat = getattr(update, "effective_chat", None)
        if admin_id and (chat is None or chat.id != admin_id):
            try:
                await self.notifier.send_message(
                    admin_id, f"Bot bir hata aldı: {type(context.error).__name__}: {context.error}"
                )
            except Exception:
                logger.exception("admin_error_notify_failed")

    async def _agent_turn(self, update: Update, message: str) -> None:
        chat = update.effective_chat
        chat_id = chat.id if chat else (update.effective_user.id if update.effective_user else 0)
        # Telegram "yazıyor..." gostergesini 5 saniye sonra kaldiriyor; bir plan
        # turu dakika surebiliyor. Tur bitene kadar 4 saniyede bir yenile ki
        # kullanici botun calistigini gorsun.
        typing = asyncio.create_task(self._keep_typing(chat_id))
        try:
            reply = await self.agent.reply(chat_id, message)
        finally:
            typing.cancel()
        for chunk in split_for_telegram(reply.text):
            await update.effective_message.reply_text(chunk)

    async def _keep_typing(self, chat_id: int) -> None:
        while True:
            try:
                await self.notifier.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Yalnizca gosterge; basarisiz olursa turu dusurmemeli.
                logger.debug("chat_action_failed chat_id=%s", chat_id)
            await asyncio.sleep(4)

    def _router_context(self, db) -> dict:
        session = MealPlannerService(db, self.settings).current_session()
        return {
            "bot_role": "personal_family_weekly_meal_planner",
            "language": "tr",
            "can_modify_plan": bool(session and session.state not in {SessionState.APPROVED, SessionState.PUBLISHED}),
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


async def reply_menu(message, text: str, reply_markup=None) -> None:
    chunks = split_for_telegram(text)
    for index, chunk in enumerate(chunks):
        kwargs = {"parse_mode": "Markdown"}
        if reply_markup is not None and index == len(chunks) - 1:
            kwargs["reply_markup"] = reply_markup
        await message.reply_text(chunk, **kwargs)


def command_body(text: str | None) -> str:
    """Komuttan sonraki metin, satir sonlari korunarak ("/kural_ekle@Bot x" -> "x")."""
    parts = (text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def rules_text(rules: list[str], summary: list[str] = ()) -> str:
    if not rules:
        return (
            "Henüz ev kuralı yok.\n\n"
            "Eklemek için: /kural_ekle Balık kullanma\n"
            "ya da bana \"bundan sonra balık kullanma\" yazman yeter."
        )
    listed = "\n".join(f"{i}. {rule}" for i, rule in enumerate(rules, 1))
    status = ("\n\nSistem ne yapıyor:\n" + "\n".join(f"• {line}" for line in summary)) if summary else ""
    return (
        f"Ev kuralları ({len(rules)}):\n{listed}{status}\n\n"
        "Ekle: /kural_ekle <kural> · Sil: /kural_sil <numara> · Hepsini yeniden yaz: /kurallari_yaz"
    )
