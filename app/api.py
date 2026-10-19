"""Foody Android uygulamasinin konustugu JSON API.

Telegram'daki ajan ve servislerin aynisi kullanilir; uygulama yalnizca ince bir
istemcidir. Gemini anahtari sunucuda kalir, telefonda yalnizca sunucu adresi,
uygulama anahtari ve sertifika parmak izi durur.

Erisim: `Authorization: Bearer <APP_API_TOKEN>`. Sunucu HTTPS ile (kendinden
imzali sertifika) yayinlanir; uygulama sertifikanin acik anahtarini sabitler
(bkz. app/api_tls.py).
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from collections import defaultdict
from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.rules import HouseRules
from app.config import Settings
from app.db.models import Recipe, RecipeStatus, SessionState, WeeklyPlanningSession
from app.db.session import SessionLocal
from app.formatting import calorie_summary, course_label
from app.memory.rules import MealRules, RuleViolation
from app.planner.dates import TR_DAY_NAMES, week_dates
from app.planner.service import MealPlannerService
from app.recipes.service import RecipeService
from app.shopping.service import CATEGORY_ORDER, ShoppingListService
from app.shopping.units import format_shopping_quantity, to_base

logger = logging.getLogger(__name__)

MIN_TOKEN_LENGTH = 24

STATE_TEXT = {
    SessionState.DRAFT_GENERATED: "Taslak",
    SessionState.AWAITING_ADMIN_FEEDBACK: "Taslak · onay bekliyor",
    SessionState.REVISION_IN_PROGRESS: "Düzenleniyor",
    SessionState.AWAITING_APPROVAL: "Taslak · onay bekliyor",
    SessionState.APPROVED: "Onaylandı",
    SessionState.PUBLISHED: "Onaylandı ve gönderildi",
}

CATEGORY_TEXT = {
    "main": "Ana yemek",
    "meze": "Meze",
    "salad": "Salata",
    "side": "Yan yemek",
    "soup": "Çorba",
    "grain": "Pilav/tahıl",
    "pilaf": "Pilav",
    "pasta": "Makarna",
}


class RuleIn(BaseModel):
    kural: str = Field(min_length=1, max_length=1000)


class RulesIn(BaseModel):
    metin: str = Field(max_length=20000)


class ChatIn(BaseModel):
    mesaj: str = Field(min_length=1, max_length=4000)


class DiscoverIn(BaseModel):
    konu: str = Field(min_length=1, max_length=300)


class SwapIn(BaseModel):
    tarih: date
    slot: str = Field(min_length=1, max_length=64)
    tarif: str = Field(min_length=1, max_length=200)


class WeekIn(BaseModel):
    hafta: str = "aktif"


def _nutrition(recipe: Recipe) -> dict:
    n = recipe.nutrition
    return {
        "kcal": round(n.calories_kcal) if n and n.calories_kcal is not None else None,
        "protein": round(n.protein_g) if n and n.protein_g is not None else None,
        "tahmini": bool(n.estimated) if n else None,
    }


def recipe_summary(recipe: Recipe) -> dict:
    effort = (recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)
    return {
        "id": recipe.id,
        "ad": recipe.name,
        "kategori": recipe.category,
        "kategori_adi": CATEGORY_TEXT.get(recipe.category, recipe.category),
        "durum": recipe.status.value,
        "sure_dk": effort or None,
        "vejetaryen": bool(recipe.vegetarian),
        "kaynak": recipe.source or "",
        **_nutrition(recipe),
    }


def recipe_detail(recipe: Recipe, people: int) -> dict:
    scale = people / recipe.servings if recipe.servings else 1
    ingredients = []
    for ing in recipe.ingredients:
        if ing.quantity is None:
            amount = ""
        else:
            base = to_base(ing.quantity * scale, ing.unit)
            amount = format_shopping_quantity(base.quantity, base.unit)
        ingredients.append({"miktar": amount, "ad": ing.ingredient.name, "not": ing.note or ""})
    return {
        **recipe_summary(recipe),
        "porsiyon": recipe.servings,
        "kisi": people,
        "malzemeler": ingredients,
        "hazirlanis": recipe.instructions or "",
    }


def menu_json(db, session: WeeklyPlanningSession | None, settings: Settings) -> dict:
    rules = MealRules.from_db(db)
    base = {
        "kalori_goster": rules.show_calories,
        "kalori_siniri": rules.max_kcal,
        "kisi": settings.default_servings,
    }
    if session is None:
        return {**base, "plan": None}
    by_day: dict[date, list] = defaultdict(list)
    items = session.meal_plan.items if session.meal_plan else []
    for item in sorted(items, key=lambda i: (i.date, i.meal_slot)):
        by_day[item.date].append(item)
    days = []
    for day in week_dates(session.week_start):
        meals = []
        for item in by_day.get(day, []):
            meals.append(
                {
                    "slot": item.meal_slot,
                    "rol": course_label(item.meal_slot),
                    "tarif_id": item.recipe.id,
                    "tarif": item.recipe.name,
                    "kategori": item.recipe.category,
                    "porsiyon": item.servings or settings.default_servings,
                    "degisti": bool(item.admin_changed),
                    **_nutrition(item.recipe),
                }
            )
        known = [m["kcal"] for m in meals if m["kcal"] is not None]
        days.append(
            {
                "tarih": day.isoformat(),
                "gun": TR_DAY_NAMES[day.weekday()],
                "ogunler": meals,
                "toplam_kcal": sum(known) if meals and len(known) == len(meals) else None,
            }
        )
    return {
        **base,
        "plan": {
            "id": session.id,
            "hafta_baslangic": session.week_start.isoformat(),
            "hafta_bitis": session.week_end.isoformat(),
            "durum": session.state.value,
            "durum_metni": STATE_TEXT.get(session.state, session.state.value),
            "onaylanabilir": bool(items) and session.state not in (SessionState.APPROVED, SessionState.PUBLISHED),
            "versiyon": session.draft_version,
            "gunler": days,
        },
    }


def create_api_app(
    settings: Settings,
    session_factory: Callable = SessionLocal,
    agent=None,
    notifier=None,
) -> FastAPI:
    if len(settings.app_api_token) < MIN_TOKEN_LENGTH:
        raise ValueError(
            f"APP_API_TOKEN en az {MIN_TOKEN_LENGTH} karakter olmalı. "
            "`python -m app.cli uygulama-hazirla` bir tane üretir."
        )
    app = FastAPI(title="Foody API", docs_url=None, redoc_url=None, openapi_url=None)
    expected = settings.app_api_token.encode("utf-8")
    chat_id = settings.admin_telegram_user_id or 0
    state = {"agent": agent}

    async def require_token(request: Request) -> None:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        if not token or not secrets.compare_digest(token.encode("utf-8"), expected):
            # Yanlis anahtarla denemeyi yavaslatir.
            await asyncio.sleep(1)
            raise HTTPException(status_code=401, detail="Uygulama anahtarı geçersiz.")

    def get_agent():
        if state["agent"] is None:
            from app.agent.runner import MealPlannerAgent

            if not MealPlannerAgent.available(settings):
                raise HTTPException(status_code=503, detail="Asistan kapalı ya da Gemini anahtarı yok.")
            state["agent"] = MealPlannerAgent(settings, session_factory)
        return state["agent"]

    def resolve(db, hafta: str) -> WeeklyPlanningSession | None:
        planner = MealPlannerService(db, settings)
        if hafta == "bu_hafta":
            return planner.this_week_session()
        if hafta == "gelecek_hafta":
            return planner.current_session()
        return planner.active_session()

    def rules_json() -> dict:
        house = HouseRules(session_factory)
        return {"kurallar": house.active(), "ozet": house.summary()}

    def recipe_or_404(db, recipe_id: str) -> Recipe:
        recipe = db.get(Recipe, recipe_id)
        if recipe is None:
            raise HTTPException(status_code=404, detail="Tarif bulunamadı.")
        return recipe

    async def agent_answer(message: str) -> dict:
        reply = await get_agent().reply(chat_id, message)
        summary = ""
        if reply.plan_session_id:
            with session_factory() as db:
                session = db.get(WeeklyPlanningSession, reply.plan_session_id)
                if session is not None and MealRules.from_db(db).show_calories:
                    summary = calorie_summary(session)
        return {
            "metin": reply.text,
            "ok": reply.ok,
            "araclar": reply.tool_calls,
            "plan_degisti": reply.plan_session_id is not None,
            "kalori_ozeti": summary,
        }

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])

    @api.get("/durum")
    def status() -> dict:
        from app.agent.runner import MealPlannerAgent

        return {
            "ad": "Foody",
            "ajan": MealPlannerAgent.available(settings),
            "saglayici": settings.agent_provider,
            "model": settings.gemini_model if settings.agent_provider == "gemini" else settings.anthropic_model,
            "kisi": settings.default_servings,
        }

    @api.get("/menu")
    async def menu(hafta: str = "aktif") -> dict:
        from app.agent.nutrition import fill_for_rules

        with session_factory() as db:
            session = resolve(db, hafta)
            if session is not None and session.meal_plan:
                await fill_for_rules(db, settings, [i.recipe for i in session.meal_plan.items])
            return menu_json(db, session, settings)

    @api.post("/menu/onayla")
    async def approve(body: WeekIn | None = None) -> dict:
        from app.workflow import WeeklyWorkflowService

        with session_factory() as db:
            session = resolve(db, (body or WeekIn()).hafta)
            if session is None or not session.meal_plan or not session.meal_plan.items:
                raise HTTPException(status_code=404, detail="Onaylanacak menü yok.")
            if session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
                raise HTTPException(status_code=409, detail="Bu menü zaten onaylı.")
            try:
                MealPlannerService(db, settings).approve(session)
            except RuleViolation as error:
                raise HTTPException(status_code=422, detail=f"Onaylanamadı: {error}") from error
            message = "Menü onaylandı."
            if notifier is not None and settings.all_recipient_ids:
                try:
                    await WeeklyWorkflowService(db, settings, notifier).publish_final(session)
                    message = "Menü onaylandı ve alıcılara Telegram'dan gönderildi."
                except Exception:
                    logger.exception("app_publish_failed session_id=%s", session.id)
                    message = "Menü onaylandı ama alıcılara gönderilemedi."
            logger.info("app_menu_approved session_id=%s", session.id)
            return {"mesaj": message, **menu_json(db, session, settings)}

    @api.post("/menu/degistir")
    async def swap(body: SwapIn) -> dict:
        from app.agent.tools import MealAgentToolset

        estimator = None
        if settings.agent_provider == "gemini" and settings.gemini_api_key and state["agent"] is not None:
            estimator = state["agent"].estimator()
        toolset = MealAgentToolset(settings, session_factory, estimator=estimator)
        tool = next(t for t in toolset.build() if t.name == "ogun_degistir")
        text = await tool.call(
            {"tarih": body.tarih.isoformat(), "yeni_tarif": body.tarif, "ogun_slotu": body.slot,
             "gerekce": "Uygulamadan değiştirildi"}
        )
        if toolset.touched_session_id is None:
            raise HTTPException(status_code=422, detail=text)
        with session_factory() as db:
            return {"mesaj": text, **menu_json(db, db.get(WeeklyPlanningSession, toolset.touched_session_id), settings)}

    @api.get("/tarifler")
    def recipes(durum: str = "onayli", q: str = "", kategori: str = "") -> dict:
        with session_factory() as db:
            service = RecipeService(db)
            rows = service.list_candidates() if durum == "aday" else service.list_recipes()
            needle = q.casefold().strip()
            if needle:
                rows = [
                    r for r in rows
                    if needle in r.name.casefold() or any(needle in i.ingredient.name.casefold() for i in r.ingredients)
                ]
            if kategori:
                rows = [r for r in rows if r.category == kategori]
            return {"tarifler": [recipe_summary(r) for r in rows]}

    @api.get("/tarifler/{recipe_id}")
    def recipe(recipe_id: str, kisi: int = 0) -> dict:
        with session_factory() as db:
            people = kisi if 0 < kisi <= 30 else settings.default_servings
            return recipe_detail(recipe_or_404(db, recipe_id), people)

    @api.post("/tarifler/{recipe_id}/onayla")
    def approve_recipe(recipe_id: str) -> dict:
        with session_factory() as db:
            recipe = recipe_or_404(db, recipe_id)
            if recipe.status != RecipeStatus.CANDIDATE:
                raise HTTPException(status_code=409, detail="Bu tarif aday değil.")
            recipe.status = RecipeStatus.APPROVED
            db.commit()
            logger.info("app_recipe_approved")
            return {"mesaj": f"{recipe.name} tarif listene eklendi.", "tarif": recipe_summary(recipe)}

    @api.post("/tarifler/{recipe_id}/cikar")
    def disable_recipe(recipe_id: str) -> dict:
        with session_factory() as db:
            recipe = recipe_or_404(db, recipe_id)
            recipe.status = RecipeStatus.INACTIVE
            db.commit()
            logger.info("app_recipe_disabled")
            return {"mesaj": f"{recipe.name} listeden çıkarıldı.", "tarif": recipe_summary(recipe)}

    @api.get("/alisveris")
    def shopping(hafta: str = "aktif") -> dict:
        with session_factory() as db:
            session = resolve(db, hafta)
            if session is None or not session.meal_plan or not session.meal_plan.items:
                return {"hafta_baslangic": None, "gruplar": []}
            items = ShoppingListService(db, settings).generate(session.meal_plan)
            grouped: dict[str, list] = defaultdict(list)
            for item in items:
                grouped[item.category].append(
                    {"anahtar": f"{item.name.casefold()}|{item.unit or ''}", "ad": item.name, "metin": item.format()}
                )
            order = [c for c in CATEGORY_ORDER if c in grouped] + [c for c in grouped if c not in CATEGORY_ORDER]
            return {
                "hafta_baslangic": session.week_start.isoformat(),
                "gruplar": [{"kategori": c, "kalemler": grouped[c]} for c in order],
            }

    @api.get("/kurallar")
    def rules() -> dict:
        return rules_json()

    @api.post("/kurallar")
    def add_rule(body: RuleIn) -> dict:
        added, detail = HouseRules(session_factory).add(body.kural)
        return {"eklendi": added, "mesaj": "Kural eklendi." if added else detail, **rules_json()}

    @api.post("/kurallar/sil")
    def remove_rule(body: RuleIn) -> dict:
        if not HouseRules(session_factory).remove(body.kural):
            raise HTTPException(status_code=404, detail="Bu kural bulunamadı.")
        return {"mesaj": "Kural silindi.", **rules_json()}

    @api.put("/kurallar")
    def replace_rules(body: RulesIn) -> dict:
        try:
            HouseRules(session_factory).replace(body.metin)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"mesaj": "Kurallar kaydedildi.", **rules_json()}

    @api.get("/sohbet")
    def history() -> dict:
        agent_ = state["agent"]
        turns = agent_.store.history(chat_id) if agent_ is not None else []
        return {"mesajlar": [{"kullanici": t["role"] == "user", "metin": t["content"]} for t in turns]}

    @api.post("/sohbet")
    async def chat(body: ChatIn) -> dict:
        return await agent_answer(body.mesaj)

    @api.post("/kesif")
    async def discover(body: DiscoverIn) -> dict:
        from app.agent.prompts import discovery_prompt

        return await agent_answer(discovery_prompt(body.konu, limit=3))

    app.include_router(api)
    return app
