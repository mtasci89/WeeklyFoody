from __future__ import annotations

from collections import Counter
from html import escape
from typing import Callable, Literal
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote
from pydantic import BaseModel, Field

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import PantryItem, Preference, Recipe, RecipeStatus, WeeklyPlanningSession, SessionState
from app.db.session import SessionLocal

SessionFactory = Callable[[], Session]


class AssistantRequest(BaseModel):
    action: Literal["chat", "generate", "approve"] = "chat"
    message: str = Field(default="", max_length=2000)
    session_id: str | None = None
    version: int | None = None



def create_web_app(settings: Settings, session_factory: SessionFactory = SessionLocal, notifier=None) -> FastAPI:
    app = FastAPI(title="WeeklyFoody Panel", docs_url=None, redoc_url=None)

    def require_auth(request: Request) -> str:
        token = request.query_params.get("token") or request.headers.get("x-panel-token", "")
        if settings.web_panel_token and token != settings.web_panel_token:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return token

    @app.get("/", response_class=HTMLResponse)
    def assistant_screen(request: Request):
        token = require_auth(request)
        html = Path(__file__).with_name("panel.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__PANEL_TOKEN__", escape(token, quote=True)), headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    def assistant_data(db, session=None, reply=""):
        from app.planner.service import MealPlannerService
        from app.formatting import format_date_range, course_label
        from app.planner.dates import TR_DAY_NAMES
        from app.shopping.service import ShoppingListService
        sessions = db.scalars(select(WeeklyPlanningSession).order_by(WeeklyPlanningSession.week_start.desc()).limit(16)).all()
        session = session or MealPlannerService(db, settings).current_session()
        labels = {SessionState.PUBLISHED: "Gönderildi", SessionState.APPROVED: "Gönderim bekliyor"}
        plan = None
        if session and session.meal_plan:
            grouped = {}
            for item in sorted(session.meal_plan.items, key=lambda i: (i.date, i.meal_slot)):
                day = grouped.setdefault(item.date, {"name": TR_DAY_NAMES[item.date.weekday()], "label": item.date.strftime("%d.%m"), "meals": []})
                day["meals"].append({"name": item.recipe.name, "role": course_label(item.meal_slot), "servings": item.servings or settings.default_servings, "changed": item.admin_changed})
            shopping = ShoppingListService(db, settings)
            plan = {"id": session.id, "version": session.draft_version, "state": session.state.value,
                    "status": labels.get(session.state, "Onay bekleyen taslak"),
                    "label": format_date_range(session.week_start, session.week_end), "days": list(grouped.values()),
                    "shopping": shopping.format(shopping.generate(session.meal_plan)), "can_publish": notifier is not None}
        return {"plan": plan, "sessions": [{"id": item.id, "label": format_date_range(item.week_start, item.week_end)} for item in sessions], "can_publish": notifier is not None, "reply": reply}

    @app.get("/api/assistant")
    def assistant_state(request: Request, session_id: str | None = None):
        require_auth(request)
        with session_factory() as db:
            session = db.get(WeeklyPlanningSession, session_id) if session_id else None
            if session_id and not session:
                raise HTTPException(404, "Menü bulunamadı.")
            return JSONResponse(assistant_data(db, session), headers={"Cache-Control": "no-store"})

    @app.post("/api/assistant")
    async def assistant_action(request: Request, body: AssistantRequest):
        require_auth(request)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Bu kaynaktan işlem yapılamaz.")
        from app.bot.intents import NaturalLanguageRouter
        from app.llm.base import Intent
        from app.planner.service import MealPlannerService
        from app.planner.revision import RevisionService
        from app.workflow import WeeklyWorkflowService
        from app.formatting import format_meal_plan, format_candidate_recipes, format_recipe_detail
        with session_factory() as db:
            planner = MealPlannerService(db, settings)
            session = db.get(WeeklyPlanningSession, body.session_id) if body.session_id else planner.current_session()
            if body.session_id and not session:
                raise HTTPException(404, "Menü bulunamadı.")
            if session and (body.session_id != session.id or body.version != session.draft_version):
                raise HTTPException(409, "Menü güncellendi. Son sürümü inceleyip isteğini tekrar gönder.")
            message = body.message.strip()
            try:
                if body.action == "generate":
                    session = await planner.create_or_get_weekly_session(session.week_start if session else None, regenerate=bool(session))
                    return assistant_data(db, session, "Menüyü hazırladım. İstediğin günleri değiştirebilir, hazır olduğunda onaylayabilirsin.")
                if body.action == "approve":
                    if not session:
                        raise ValueError("Önce bir menü hazırlayalım.")
                    if notifier is None:
                        raise HTTPException(503, "Gönderim için Telegram botunun çalışıyor olması gerekiyor.")
                    planner.approve(session)
                    sent = await WeeklyWorkflowService(db, settings, notifier).publish_final(session)
                    return assistant_data(db, session, "Güncel menü ve alışveriş listesi gönderildi." if sent else "Bu sürüm zaten gönderildi.")
                if not message:
                    raise ValueError("Nasıl yardımcı olayım? Bir mesaj yaz.")
                if message.casefold() in {"iptal", "vazgeç", "vazgec"}:
                    if session:
                        session.context = {k: v for k, v in (session.context or {}).items() if k not in {"pending_revision", "clarification"}}
                        db.commit()
                    return assistant_data(db, session, "Bekleyen isteği iptal ettim. Menü aynı kaldı.")
                router = NaturalLanguageRouter(settings)
                context = {"has_active_plan": bool(session), "can_modify_plan": bool(session), "current_plan": format_meal_plan(session) if session else None, "session_state": session.state.value if session else None}
                routed = await router.route(message, context)
                if routed.clarification_question:
                    return assistant_data(db, session, routed.clarification_question)
                pending = session and (session.context or {}).get("pending_revision")
                if routed.intent == Intent.MODIFY_PLAN or pending and routed.intent in {Intent.UNKNOWN, Intent.GENERAL_QUESTION}:
                    if not session:
                        raise ValueError("Önce yeni bir menü hazırlayalım; sonra birlikte düzenleyebiliriz.")
                    session = await RevisionService(db, settings).revise(session, message)
                    answer = (session.context or {}).get("clarification") or "Değişiklikleri taslağa kaydettim. Menü ve alışveriş listesi güncellendi. İnceledikten sonra onaylayıp gönderebilirsin."
                elif routed.intent == Intent.APPROVE_PLAN:
                    answer = "Son menüyü inceleyip ‘Onayla ve gönder’ düğmesine basabilirsin."
                elif routed.intent == Intent.REGENERATE_PLAN:
                    answer = "Bütün haftayı değiştirmek için ‘Baştan hazırla’ düğmesini kullanabilirsin. Tek bir yemek için gün ve yemek adını yaz."
                elif routed.intent == Intent.ADD_RECIPE and routed.recipe_text:
                    recipe = RecipeService(db).add_recipe_from_text(routed.recipe_text)
                    answer = f"{recipe.name} tarifini kütüphaneye ekledim."
                elif routed.intent == Intent.APPROVE_RECIPE_CANDIDATE:
                    ok = RecipeService(db).approve_candidate(routed.recipe_name or "")
                    answer = "Tarifi kütüphanene ekledim." if ok else "Hangi aday tarifi onaylayayım? Tarifin tam adını yaz."
                elif routed.intent == Intent.SHOW_RECIPE_CANDIDATES:
                    answer = format_candidate_recipes(RecipeService(db).list_candidates())
                elif routed.intent == Intent.DISCOVER_RECIPE:
                    answer = format_candidate_recipes(await RecipeService(db).discover_recipes(routed.discovery_query or message, settings, limit=3))
                elif routed.intent == Intent.SHOW_RECIPE:
                    recipe = RecipeService(db).find_recipe(routed.recipe_name or message)
                    answer = format_recipe_detail(recipe) if recipe else "Bu tarifi bulamadım. Tarif kütüphanesine bakabilirsin."
                elif routed.intent == Intent.ADD_PREFERENCE and routed.preference:
                    from app.memory.preferences import PreferenceService
                    from app.db.models import PreferenceType
                    PreferenceService(db).add(routed.preference.rule, PreferenceType.HARD, source="web")
                    answer = "Tercihini kaydettim. Bundan sonraki seçimlerde dikkate alacağım."
                elif routed.intent == Intent.SHOW_SHOPPING_LIST:
                    answer = "Menünün altındaki ‘Alışveriş listesi’ düğmesinden güncel listeyi açabilirsin."
                elif routed.intent == Intent.SHOW_MENU:
                    answer = format_meal_plan(session) if session else "Henüz menü yok. ‘Yeni menü hazırla’ ile başlayalım."
                else:
                    answer = await router.answer_general_question(message, context)
                return assistant_data(db, session, answer)
            except HTTPException:
                raise
            except ValueError as exc:
                db.rollback()
                raise HTTPException(400, str(exc)) from exc
            except Exception as exc:
                db.rollback()
                import logging
                logging.getLogger(__name__).exception("assistant_action_failed")
                raise HTTPException(503, "İşlemi tamamlayamadım. Menüye bakıp tekrar deneyebilirsin. Gönderim yarıda kaldıysa tekrar onayladığında kaldığı yerden devam eder.") from exc

    @app.get("/library", response_class=HTMLResponse)
    def dashboard(request: Request) -> str:
        token = require_auth(request)
        with session_factory() as db:
            recipes = db.scalars(select(Recipe)).all()
            counts = Counter(recipe.category for recipe in recipes if recipe.status == RecipeStatus.APPROVED)
            candidate_count = sum(1 for recipe in recipes if recipe.status == RecipeStatus.CANDIDATE)
            inactive_count = sum(1 for recipe in recipes if recipe.status == RecipeStatus.INACTIVE)
            body = [
                "<section class='hero'>",
                "<h1>WeeklyFoody Tarif Paneli</h1>",
                "<p>Tarif kütüphanesi, aday tarifler, pantry ve tercihler.</p>",
                "</section>",
                "<section class='stats'>",
                stat_card("Toplam approved", str(sum(counts.values()))),
                stat_card("Ana yemek", str(counts.get("main", 0))),
                stat_card("Meze", str(counts.get("meze", 0))),
                stat_card("Salata", str(counts.get("salad", 0))),
                stat_card("Yan/çorba", str(sum(counts.get(cat, 0) for cat in ("side", "soup", "grain", "pasta", "pilaf")))),
                stat_card("Aday", str(candidate_count)),
                stat_card("Pasif", str(inactive_count)),
                "</section>",
                "<section class='quick'>",
                link_button("Tüm tarifler", "/recipes", token),
                link_button("Ana yemekler", "/recipes?category=main", token),
                link_button("Mezeler", "/recipes?category=meze", token),
                link_button("Salatalar", "/recipes?category=salad", token),
                link_button("Yan yemekler", "/recipes?role=side", token),
                link_button("Aday tarifler", "/candidates", token),
                link_button("Pantry", "/pantry", token),
                link_button("Tercihler", "/preferences", token),
                "</section>",
            ]
            return page("WeeklyFoody Panel", "\n".join(body), token)

    @app.get("/recipes", response_class=HTMLResponse)
    def recipes(request: Request, category: str | None = None, role: str | None = None, status: str = "approved", q: str = "") -> str:
        token = require_auth(request)
        with session_factory() as db:
            recipes = list(db.scalars(select(Recipe).order_by(Recipe.name)).all())
            recipes = filter_recipes(recipes, category=category, role=role, status=status, query=q)
            chips = [
                link_button("Tümü", "/recipes", token),
                link_button("Ana", "/recipes?category=main", token),
                link_button("Meze", "/recipes?category=meze", token),
                link_button("Salata", "/recipes?category=salad", token),
                link_button("Yan", "/recipes?role=side", token),
                link_button("Aday", "/recipes?status=candidate", token),
            ]
            rows = "\n".join(recipe_card(recipe, token) for recipe in recipes) or "<p class='empty'>Tarif bulunamadı.</p>"
            body = f"""
            <section class='toolbar'>
              <h1>Tarifler</h1>
              <form method='get' action='/recipes'>
                {token_input(token)}
                <input name='q' value='{escape(q)}' placeholder='Tarif ara'>
                <button>Ara</button>
              </form>
            </section>
            <section class='chips'>{''.join(chips)}</section>
            <section class='grid'>{rows}</section>
            """
            return page("Tarifler", body, token)

    @app.get("/recipes/{recipe_id}", response_class=HTMLResponse)
    def recipe_detail(recipe_id: str, request: Request) -> str:
        token = require_auth(request)
        with session_factory() as db:
            recipe = db.get(Recipe, recipe_id)
            if not recipe:
                raise HTTPException(status_code=404, detail="Recipe not found")
            ingredients = "\n".join(
                f"<li>{quantity_text(item.quantity, item.unit)} {escape(item.ingredient.name)}</li>".strip()
                for item in recipe.ingredients
            )
            body = f"""
            <section class='detail'>
              <p><a href='{href('/recipes', token)}'>← Tariflere dön</a></p>
              <h1>{escape(recipe.name)}</h1>
              <div class='meta'>
                <span>{escape(recipe.category)}</span>
                <span>{escape(recipe.status.value)}</span>
                <span>{recipe.servings} porsiyon</span>
                <span>{(recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)} dk</span>
              </div>
              <h2>Malzemeler</h2>
              <ul>{ingredients or '<li>Malzeme detayı yok.</li>'}</ul>
              <h2>Hazırlık</h2>
              <p>{escape(recipe.instructions or 'Hazırlık notu yok.')}</p>
              <h2>Notlar</h2>
              <p>{escape(recipe.notes or recipe.source or 'Not yok.')}</p>
            </section>
            """
            return page(recipe.name, body, token)

    @app.get("/candidates", response_class=HTMLResponse)
    def candidates(request: Request) -> str:
        token = require_auth(request)
        with session_factory() as db:
            recipes = db.scalars(select(Recipe).where(Recipe.status == RecipeStatus.CANDIDATE).order_by(Recipe.created_at.desc())).all()
            rows = "\n".join(recipe_card(recipe, token) for recipe in recipes) or "<p class='empty'>Aday tarif yok.</p>"
            return page("Aday Tarifler", f"<h1>Aday Tarifler</h1><section class='grid'>{rows}</section>", token)

    @app.get("/pantry", response_class=HTMLResponse)
    def pantry(request: Request) -> str:
        token = require_auth(request)
        with session_factory() as db:
            items = db.scalars(select(PantryItem).order_by(PantryItem.ingredient_name)).all()
            rows = "".join(f"<li>{escape(item.ingredient_name)}</li>" for item in items) or "<li>Pantry boş.</li>"
            return page("Pantry", f"<h1>Pantry</h1><ul class='list'>{rows}</ul>", token)

    @app.get("/preferences", response_class=HTMLResponse)
    def preferences(request: Request) -> str:
        token = require_auth(request)
        with session_factory() as db:
            items = db.scalars(select(Preference).where(Preference.active.is_(True)).order_by(Preference.created_at.desc())).all()
            rows = "".join(f"<li><strong>{escape(item.type.value)}</strong>: {escape(item.rule)}</li>" for item in items) or "<li>Kayıtlı tercih yok.</li>"
            return page("Tercihler", f"<h1>Tercihler</h1><ul class='list'>{rows}</ul>", token)

    @app.get("/api/recipes")
    def recipes_api(request: Request, status: str = "approved") -> JSONResponse:
        require_auth(request)
        with session_factory() as db:
            recipes = db.scalars(select(Recipe).order_by(Recipe.name)).all()
            data = [
                {
                    "id": recipe.id,
                    "name": recipe.name,
                    "category": recipe.category,
                    "status": recipe.status.value,
                    "servings": recipe.servings,
                    "ingredient_count": len(recipe.ingredients),
                }
                for recipe in filter_recipes(list(recipes), status=status)
            ]
            return JSONResponse(data)

    return app


def filter_recipes(recipes: list[Recipe], category: str | None = None, role: str | None = None, status: str = "approved", query: str = "") -> list[Recipe]:
    if status:
        recipes = [recipe for recipe in recipes if recipe.status.value == status]
    if category:
        recipes = [recipe for recipe in recipes if recipe.category == category]
    if role == "side":
        recipes = [recipe for recipe in recipes if recipe.category in {"side", "soup", "grain", "pasta", "pilaf"}]
    if query:
        needle = query.casefold().strip()
        recipes = [recipe for recipe in recipes if needle in recipe.name.casefold()]
    return recipes


def page(title: str, body: str, token: str) -> str:
    return f"""
    <!doctype html>
    <html lang='tr'>
    <head>
      <meta charset='utf-8'>
      <meta name='viewport' content='width=device-width, initial-scale=1'>
      <title>{escape(title)}</title>
      <style>{CSS}</style>
    </head>
    <body>
      <nav>
        <a href='{href('/', token)}'>Panel</a>
        <a href='{href('/recipes', token)}'>Tarifler</a>
        <a href='{href('/candidates', token)}'>Adaylar</a>
        <a href='{href('/pantry', token)}'>Pantry</a>
        <a href='{href('/preferences', token)}'>Tercihler</a>
      </nav>
      <main>{body}</main>
    </body>
    </html>
    """


def stat_card(label: str, value: str) -> str:
    return f"<article><span>{escape(label)}</span><strong>{escape(value)}</strong></article>"


def recipe_card(recipe: Recipe, token: str) -> str:
    effort = (recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)
    return f"""
    <article class='card'>
      <a href='{href(f'/recipes/{recipe.id}', token)}'><h2>{escape(recipe.name)}</h2></a>
      <p>{escape(recipe.category)} · {escape(recipe.status.value)} · {recipe.servings} porsiyon · {effort} dk</p>
      <p>{len(recipe.ingredients)} malzeme</p>
    </article>
    """


def link_button(label: str, path: str, token: str) -> str:
    return f"<a class='button' href='{href(path, token)}'>{escape(label)}</a>"


def href(path: str, token: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}token={escape(quote(token, safe=''))}" if token else path


def token_input(token: str) -> str:
    return f"<input type='hidden' name='token' value='{escape(token)}'>" if token else ""


def quantity_text(quantity: float | None, unit: str | None) -> str:
    if quantity is None:
        return ""
    return f"{quantity:g} {escape(unit or '')}".strip()


CSS = """
:root{color-scheme:light;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f7f7f4;color:#222}
body{margin:0}
nav{position:sticky;top:0;display:flex;gap:18px;align-items:center;padding:14px 28px;background:#fff;border-bottom:1px solid #ddd;z-index:1}
nav a{color:#222;text-decoration:none;font-weight:700}
main{max-width:1120px;margin:0 auto;padding:28px}
h1{font-size:30px;margin:0 0 14px}
h2{font-size:18px;margin:0 0 8px}
a{color:#1f5f5b}
.hero{padding:28px 0 18px}
.hero p{font-size:18px;color:#555}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:18px 0 28px}
.stats article,.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:16px}
.stats span{display:block;color:#666;font-size:13px}
.stats strong{font-size:28px}
.quick,.chips{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}
.button,button{border:1px solid #1f5f5b;background:#fff;color:#1f5f5b;border-radius:8px;padding:9px 12px;text-decoration:none;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:14px}
.card p{margin:6px 0;color:#555}
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
input{padding:10px 12px;border:1px solid #ccc;border-radius:8px;min-width:240px}
.detail{background:#fff;border:1px solid #ddd;border-radius:8px;padding:22px}
.meta{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 24px}
.meta span{background:#edf3f1;border-radius:999px;padding:6px 10px;font-size:13px}
.list{background:#fff;border:1px solid #ddd;border-radius:8px;padding:20px 20px 20px 40px}
.empty{color:#666}
"""

