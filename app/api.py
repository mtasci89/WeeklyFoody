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
import base64
import binascii
import logging
import secrets
from collections import defaultdict
from collections.abc import Callable
from typing import Literal
from datetime import date

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.rules import HouseRules
from app.agent.runner import GORSEL_TURLERI, Gorsel
from app.config import Settings, is_weekly_slot
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


class ImageIn(BaseModel):
    mime: str = Field(max_length=40)
    # base64; telefon gondermeden once kucultur (~1600 px JPEG), 6 MB ust sinir.
    veri: str = Field(min_length=8, max_length=8_000_000)


class ChatIn(BaseModel):
    mesaj: str = Field(default="", max_length=4000)
    gorseller: list[ImageIn] = Field(default_factory=list, max_length=4)


class DiscoverIn(BaseModel):
    konu: str = Field(min_length=1, max_length=300)


class SwapIn(BaseModel):
    # ISO tarih ya da haftalık meze listesi için "HAFTA".
    tarih: str = Field(min_length=1, max_length=20)
    slot: str = Field(min_length=1, max_length=64)
    tarif: str = Field(min_length=1, max_length=200)
    hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif"


class AddIn(BaseModel):
    tarih: str = Field(min_length=1, max_length=20)
    tarif: str = Field(min_length=1, max_length=200)
    hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif"


class FreshIn(BaseModel):
    tarih: str = Field(min_length=1, max_length=20)
    slot: str = Field(default="", max_length=64)
    istek: str = Field(default="", max_length=500)
    hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif"


class RemoveIn(BaseModel):
    tarih: str = Field(min_length=1, max_length=20)
    slot: str = Field(min_length=1, max_length=64)
    hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif"


FINAL_STATES = (SessionState.APPROVED, SessionState.PUBLISHED)


def draft_session(planner: MealPlannerService) -> WeeklyPlanningSession | None:
    """Uygulamadaki "Taslak": onay bekleyen plan (önce gelecek hafta, sonra bu hafta)."""
    for session in (planner.current_session(), planner.this_week_session()):
        if session is not None and session.state not in FINAL_STATES:
            return session
    return None


def approved_session(db, planner: MealPlannerService) -> WeeklyPlanningSession | None:
    """Uygulamadaki "Onaylı menü": bu haftanın onaylı menüsü, yoksa en son onaylanan."""
    current = planner.this_week_session()
    if current is not None and current.state in FINAL_STATES:
        return current
    from sqlalchemy import select

    return db.scalar(
        select(WeeklyPlanningSession)
        .where(WeeklyPlanningSession.state.in_(FINAL_STATES))
        .order_by(WeeklyPlanningSession.week_start.desc())
        .limit(1)
    )


def plan_snapshot(db, settings: Settings) -> dict[str, dict[tuple[str, str], str]]:
    """Bu ve gelecek haftanın planı: {oturum: {(tarih|HAFTA, slot): tarif}}.
    Asistan turundan önce alınır; sonra neyin değiştiği gösterilir."""
    planner = MealPlannerService(db, settings)
    result = {}
    for session in {planner.this_week_session(), planner.current_session()} - {None}:
        items = session.meal_plan.items if session.meal_plan else []
        result[session.id] = {
            ("HAFTA" if is_weekly_slot(i.meal_slot) else i.date.isoformat(), i.meal_slot): i.recipe.name
            for i in items
        }
    return result


def plan_changes(before: dict[tuple[str, str], str], after: dict[tuple[str, str], str]) -> list[dict]:
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            changes.append({"tarih": key[0], "slot": key[1], "eski": old, "yeni": new})
    return changes


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
    weekly = []
    for item in sorted(items, key=lambda i: (i.date, i.meal_slot)):
        (weekly if is_weekly_slot(item.meal_slot) else by_day[item.date]).append(item)

    def meal(item) -> dict:
        return {
            "slot": item.meal_slot,
            "rol": "Meze" if is_weekly_slot(item.meal_slot) else course_label(item.meal_slot),
            "tarif_id": item.recipe.id,
            "tarif": item.recipe.name,
            "kategori": item.recipe.category,
            "porsiyon": item.servings or settings.default_servings,
            "degisti": bool(item.admin_changed),
            # Kütüphanede olmayan, bu hafta denenecek yemek (aday tarif).
            "yeni": item.recipe.status == RecipeStatus.CANDIDATE,
            **_nutrition(item.recipe),
        }

    days = []
    for day in week_dates(session.week_start):
        meals = [meal(item) for item in by_day.get(day, [])]
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
            # Günlere bölünmeyen, haftalık meze listesi (kalori toplamlarına girmez).
            "mezeler": [meal(item) for item in weekly],
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
            state["agent"] = MealPlannerAgent(settings, session_factory, notifier=notifier)
        return state["agent"]

    def json_asker():
        """Modelden yapılandırılmış cevap isteyen fonksiyon (Gemini yoksa None)."""
        if settings.agent_provider != "gemini" or not settings.gemini_api_key:
            return None
        try:
            estimator = get_agent().estimator()
        except HTTPException:
            return None
        return getattr(estimator, "ask_json", None)

    async def complete(db, session) -> None:
        """Menüdeki, malzemesi kaydedilmemiş tarifleri tamamlar (tarif ve alışveriş için)."""
        if session is None or not session.meal_plan:
            return
        from app.agent.recipe_fill import fill_recipes

        await fill_recipes(db, json_asker(), [i.recipe for i in session.meal_plan.items])

    def resolve(db, hafta: str) -> WeeklyPlanningSession | None:
        planner = MealPlannerService(db, settings)
        if hafta == "bu_hafta":
            return planner.this_week_session()
        if hafta == "gelecek_hafta":
            return planner.current_session()
        if hafta == "taslak":
            return draft_session(planner)
        if hafta == "onayli":
            return approved_session(db, planner)
        return planner.active_session()

    def rules_json() -> dict:
        house = HouseRules(session_factory)
        return {"kurallar": house.active(), "ozet": house.summary()}

    def recipe_or_404(db, recipe_id: str) -> Recipe:
        recipe = db.get(Recipe, recipe_id)
        if recipe is None:
            raise HTTPException(status_code=404, detail="Tarif bulunamadı.")
        return recipe

    async def agent_answer(message: str, images=None, timeout: int | None = None) -> dict:
        agent_ = get_agent()
        with session_factory() as db:
            before = plan_snapshot(db, settings)
        reply = await agent_.reply(chat_id, message, images=images or None, timeout=timeout, channel="uygulama")
        summary = ""
        menu = None
        changes: list[dict] = []
        if reply.plan_session_id:
            with session_factory() as db:
                session = db.get(WeeklyPlanningSession, reply.plan_session_id)
                if session is not None:
                    if MealRules.from_db(db).show_calories:
                        summary = calorie_summary(session)
                    # Uygulama menüyü sohbetin içinde kart olarak gösterir;
                    # asistanın metni menüyü tekrar yazmak zorunda kalmaz.
                    menu = menu_json(db, session, settings)
                    after = plan_snapshot(db, settings).get(session.id, {})
                    changes = plan_changes(before.get(session.id, {}), after)
        return {
            "metin": reply.text,
            "ok": reply.ok,
            "araclar": reply.tool_calls,
            "plan_degisti": reply.plan_session_id is not None,
            "kalori_ozeti": summary,
            "menu": menu,
            "degisiklikler": changes,
        }

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])

    @api.get("/durum")
    def status() -> dict:
        from app.agent.runner import MealPlannerAgent

        from app.updater import current_version, update_running

        version = current_version()
        return {
            "ad": "Foody",
            "surum": version["surum"],
            "aciklama": version["aciklama"],
            "guncelleniyor": update_running(),
            "ajan": MealPlannerAgent.available(settings),
            "saglayici": settings.agent_provider,
            "model": settings.gemini_model if settings.agent_provider == "gemini" else settings.anthropic_model,
            "kisi": settings.default_servings,
        }

    @api.post("/guncelle")
    def self_update() -> dict:
        from app.updater import start_update

        return {"mesaj": start_update(settings.admin_telegram_user_id or None)}

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
            await complete(db, session)
            message = "Menü onaylandı. Onaylı menü, tarifleri ve alışveriş listesi uygulamada hazır."
            if settings.telegram_menu_messages and notifier is not None and settings.all_recipient_ids:
                try:
                    await WeeklyWorkflowService(db, settings, notifier).publish_final(session)
                    message = "Menü onaylandı ve alıcılara Telegram'dan gönderildi."
                except Exception:
                    logger.exception("app_publish_failed session_id=%s", session.id)
                    message = "Menü onaylandı ama alıcılara gönderilemedi."
            logger.info("app_menu_approved session_id=%s", session.id)
            return {"mesaj": message, **menu_json(db, session, settings)}

    async def run_menu_tool(name: str, args: dict) -> dict:
        """Uygulamadaki elle düzenleme, asistanın aynı (kural denetimli) aracıyla yapılır."""
        from app.agent.tools import MealAgentToolset

        estimator = None
        if settings.agent_provider == "gemini" and settings.gemini_api_key and state["agent"] is not None:
            estimator = state["agent"].estimator()
        toolset = MealAgentToolset(settings, session_factory, estimator=estimator)
        tool = next(t for t in toolset.build() if t.name == name)
        text = await tool.call(args)
        # Çeşitlilik gözlemleri modele yöneliktir; uygulamaya kısa sonucu göster.
        text = text.split("\nÇeşitlilik")[0].strip()
        if toolset.touched_session_id is None:
            raise HTTPException(status_code=422, detail=text)
        with session_factory() as db:
            return {"mesaj": text, **menu_json(db, db.get(WeeklyPlanningSession, toolset.touched_session_id), settings)}

    @api.post("/menu/degistir")
    async def swap(body: SwapIn) -> dict:
        return await run_menu_tool(
            "ogun_degistir",
            {"tarih": body.tarih, "yeni_tarif": body.tarif, "ogun_slotu": body.slot,
             "gerekce": "Uygulamadan değiştirildi", "hafta": body.hafta},
        )

    @api.post("/menu/ekle")
    async def add_meal(body: AddIn) -> dict:
        return await run_menu_tool(
            "ogun_ekle", {"tarih": body.tarih, "tarif": body.tarif, "gerekce": "Uygulamadan eklendi", "hafta": body.hafta},
        )

    @api.post("/menu/yenisi")
    async def fresh_meal(body: FreshIn) -> dict:
        """Uygulamadaki "Yerine yeni bir şey bul": sohbet gerekmeden, kütüphanede
        olmayan bir yemek üretilip konur."""
        target = f"{body.tarih}|{body.slot}" if body.slot else body.tarih
        return await run_menu_tool(
            "yenisiyle_degistir", {"ogunler": [target], "istek": body.istek, "hafta": body.hafta},
        )

    @api.get("/menu/tarifler")
    async def menu_recipes(hafta: str = "aktif", kisi: int = 0) -> dict:
        """Bir haftanın menüsündeki tariflerin hepsi (malzemeler kişi sayısına göre,
        hazırlanış): uygulamada "Bu haftanın tarifleri" ve PDF için."""
        people = kisi if 1 <= kisi <= 20 else settings.default_servings
        with session_factory() as db:
            session = resolve(db, hafta)
            if session is None or not session.meal_plan:
                return {"hafta_baslangic": None, "durum": None, "tarifler": []}
            await complete(db, session)
            ordered = sorted(
                session.meal_plan.items, key=lambda i: (is_weekly_slot(i.meal_slot), i.date, i.meal_slot)
            )
            seen, recipes = set(), []
            for item in ordered:
                if item.recipe_id in seen:
                    continue
                seen.add(item.recipe_id)
                when = "Haftanın mezeleri" if is_weekly_slot(item.meal_slot) else TR_DAY_NAMES[item.date.weekday()]
                recipes.append({**recipe_detail(item.recipe, people), "gun": when})
            return {
                "hafta_baslangic": session.week_start.isoformat(),
                "durum": session.state.value,
                "tarifler": recipes,
            }

    @api.post("/menu/cikar")
    async def remove_meal(body: RemoveIn) -> dict:
        return await run_menu_tool(
            "ogun_cikar", {"tarih": body.tarih, "tarif_veya_slot": body.slot, "hafta": body.hafta},
        )

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
    async def recipe(recipe_id: str, kisi: int = 0) -> dict:
        from app.agent.recipe_fill import fill_recipes

        with session_factory() as db:
            people = kisi if 0 < kisi <= 30 else settings.default_servings
            found = recipe_or_404(db, recipe_id)
            # Yalnızca adıyla kayıtlı tarif açılınca tamamlanır (bir kez).
            await fill_recipes(db, json_asker(), [found])
            return recipe_detail(found, people)

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
    async def shopping(hafta: str = "aktif") -> dict:
        with session_factory() as db:
            session = resolve(db, hafta)
            if session is None or not session.meal_plan or not session.meal_plan.items:
                return {"hafta_baslangic": None, "gruplar": []}
            await complete(db, session)
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

    def decode_images(body: ChatIn) -> list[Gorsel]:
        images = []
        for image in body.gorseller:
            if image.mime not in GORSEL_TURLERI:
                raise HTTPException(status_code=422, detail=f"Desteklenmeyen görsel türü: {image.mime}")
            try:
                images.append(Gorsel(image.mime, base64.b64decode(image.veri, validate=True)))
            except (binascii.Error, ValueError) as error:
                raise HTTPException(status_code=422, detail="Görsel bozuk geldi, tekrar dene.") from error
        if not body.mesaj.strip() and not images:
            raise HTTPException(status_code=422, detail="Boş mesaj gönderilemez.")
        return images

    # --- arka plan isleri ---------------------------------------------------
    # Bir asistan turu dakikalar surebiliyor. Tek bir uzun bekleyen istek mobil
    # agda ya da uygulama arka plana gecince kopuyordu ("Sunucuya ulasilamadi"),
    # oysa sunucu isi bitiriyordu. Simdi uygulama isi baslatir, sonra kisa
    # isteklerle durumunu sorar; baglanti kopsa da is ve cevabi kaybolmaz.
    jobs: dict[str, dict] = {}
    tasks: set[asyncio.Task] = set()

    def start_job(message: str, images: list[Gorsel]) -> dict:
        import time

        now = time.monotonic()
        for old_id in [k for k, v in jobs.items() if now - v["zaman"] > 3600]:
            jobs.pop(old_id, None)
        job_id = secrets.token_urlsafe(12)
        jobs[job_id] = {"durum": "calisiyor", "sonuc": None, "hata": None, "zaman": now}

        async def run() -> None:
            try:
                jobs[job_id]["sonuc"] = await agent_answer(message, images, timeout=settings.agent_job_timeout_seconds)
                jobs[job_id]["durum"] = "bitti"
            except HTTPException as error:
                jobs[job_id].update(durum="hata", hata=str(error.detail))
            except Exception:
                logger.exception("app_job_failed")
                jobs[job_id].update(durum="hata", hata="Asistan bu isteği tamamlayamadı.")

        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        logger.info("app_job_started images=%s", len(images))
        return {"is": job_id, "durum": "calisiyor"}

    @api.post("/sohbet")
    async def chat(body: ChatIn) -> dict:
        """Eski (1.1) uygulama icin: cevabi ayni istekte bekler."""
        return await agent_answer(body.mesaj, decode_images(body))

    @api.post("/sohbet/baslat")
    async def chat_start(body: ChatIn) -> dict:
        images = decode_images(body)
        get_agent()  # asistan kapaliysa hemen 503
        return start_job(body.mesaj, images)

    @api.post("/kesif")
    async def discover(body: DiscoverIn) -> dict:
        from app.agent.prompts import discovery_prompt

        return await agent_answer(discovery_prompt(body.konu, limit=3))

    @api.post("/kesif/baslat")
    async def discover_start(body: DiscoverIn) -> dict:
        from app.agent.prompts import discovery_prompt

        get_agent()
        return start_job(discovery_prompt(body.konu, limit=3), [])

    @api.get("/is/{job_id}")
    def job_status(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Bu iş bulunamadı (sunucu yeniden başlamış olabilir).")
        return {"is": job_id, "durum": job["durum"], "sonuc": job["sonuc"], "hata": job["hata"]}

    app.include_router(api)
    return app
