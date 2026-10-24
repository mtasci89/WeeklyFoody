"""Tekrar yasağı ve "yerine yepyeni bir şey koy".

Kullanıcı: "Dünyada başka yemek yok mu? 2 gün arka arkaya karamelize soğanlı dana sote
var diyorum, onu değiştirip 2 gün arka arkaya fırında püreli tavuk koymuşsun; yeni
tarif diyorum hâlâ aynı şeyler!"
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.agent.tools import MealAgentToolset
from app.db.models import MealPlan, MealPlanItem, RecipeStatus, SessionState, WeeklyPlanningSession
from app.memory.preferences import PreferenceService
from app.planner.dates import next_week_start, week_end
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService

WEEK = next_week_start(timezone="Europe/Istanbul")
DAYS = [WEEK + timedelta(days=k) for k in range(7)]
MAINS = ["Fırında Tavuk", "Kuru Fasulye", "Izgara Köfte", "Nohut", "Sebze Yemeği", "Karnıyarık", "Mantı"]


class FakeEstimator:
    """Gerçekte NutritionEstimator(GeminiBackend.generate_json); burada yalnızca ask_json."""

    def __init__(self, ideas):
        self.ideas = ideas
        self.prompts: list[str] = []

    async def ask_json(self, prompt, schema):
        self.prompts.append(prompt)
        return json.dumps({"tarifler": self.ideas})

    async def fill_missing(self, db, recipes):
        return []


def toolset_for(db, settings, estimator=None):
    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    toolset = MealAgentToolset(settings.model_copy(update={"no_repeat_meals": True}), _Factory(), estimator=estimator)
    return toolset, {t.name: t for t in toolset.build()}


def plan(db, rows, week=WEEK):
    """rows: [(gün indeksi, slot, tarif adı)]"""
    service = RecipeService(db)
    session = WeeklyPlanningSession(week_start=week, week_end=week_end(week), state=SessionState.AWAITING_APPROVAL)
    db.add(session)
    db.flush()
    meal_plan = MealPlan(session=session, status="draft")
    db.add(meal_plan)
    db.flush()
    for index, slot, name in rows:
        meal_plan.items.append(
            MealPlanItem(date=week + timedelta(days=index), meal_slot=slot, recipe_id=service.find_recipe(name).id)
        )
    db.commit()
    return session


@pytest.fixture()
def library(db):
    service = RecipeService(db)
    for name in ("Karnıyarık", "Mantı"):
        service.upsert_recipe(
            RecipeInput(name=name, category="main", meal_type="dinner",
                        ingredients=[IngredientInput(name=f"{name} malzemesi", quantity=1, unit="adet")])
        )
    return db


def week_rows():
    return [(k, "dinner_main", MAINS[k]) for k in range(7)] + [(k, "dinner_side", "Makarna") for k in (0, 2, 4)]


# --- tekrar yasağı ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_main_already_in_the_week_is_refused(library, settings):
    plan(library, week_rows())
    _, tools = toolset_for(library, settings)

    out = await tools["ogun_degistir"].call(
        {"tarih": DAYS[3].isoformat(), "yeni_tarif": "Fırında Tavuk", "gerekce": "x", "ogun_slotu": "dinner_main"}
    )

    assert "kaydedilmedi" in out and "haftada bir kez" in out


@pytest.mark.asyncio
async def test_the_same_dish_on_consecutive_days_is_refused(library, settings):
    plan(library, week_rows())
    _, tools = toolset_for(library, settings)

    out = await tools["ogun_ekle"].call({"tarih": DAYS[1].isoformat(), "tarif": "Makarna"})

    assert "Eklenmedi" in out and "arka arkaya" in out


@pytest.mark.asyncio
async def test_plan_kaydet_refuses_repeats_and_back_to_back_days(library, settings):
    _, tools = toolset_for(library, settings)
    rows = [f"{d.isoformat()}|dinner_main|{name}" for d, name in zip(DAYS, MAINS)]
    rows[1] = f"{DAYS[1].isoformat()}|dinner_main|Fırında Tavuk"  # Pzt + Salı aynı

    out = await tools["plan_kaydet"].call({"ogunler": rows})

    assert "Plan kaydedilmedi" in out
    assert "2 kez" in out and "arka arkaya" in out


@pytest.mark.asyncio
async def test_back_to_back_across_the_week_boundary_is_refused(library, settings):
    previous = WEEK - timedelta(days=7)
    plan(library, [(6, "dinner_main", "Mantı")], week=previous)  # önceki haftanın pazarı
    _, tools = toolset_for(library, settings)
    rows = [f"{d.isoformat()}|dinner_main|{name}" for d, name in zip(DAYS, ["Mantı", *MAINS[:6]])]

    out = await tools["plan_kaydet"].call({"ogunler": rows})

    assert "komşu hafta" in out


@pytest.mark.asyncio
async def test_a_varied_week_is_accepted(library, settings):
    _, tools = toolset_for(library, settings)
    rows = [f"{d.isoformat()}|dinner_main|{name}" for d, name in zip(DAYS, MAINS)]
    assert "kaydedildi" in await tools["plan_kaydet"].call({"ogunler": rows})


# --- yepyeni yemek -------------------------------------------------------------------


def idea(name, *ingredients, **extra):
    return {"ad": name, "malzemeler": list(ingredients) or ["1 adet x", "2 adet y"], "hazirlanis": "Pişir.", **extra}


@pytest.mark.asyncio
async def test_yenisiyle_degistir_puts_a_dish_that_is_new_and_allowed(library, settings):
    session = plan(library, week_rows())
    PreferenceService(library).add("balık kullanma")
    estimator = FakeEstimator([
        idea("Fırında Tavuk"),  # zaten kütüphanede
        idea("Somonlu Teriyaki", "500 gr somon", "3 yemek kaşığı soya sosu"),  # kurala aykırı
        idea("Kore Usulü Bulgogi", "600 gr dana bonfile", "4 yemek kaşığı soya sosu", "1 adet armut",
             mutfak="Kore", neden="Tatlı-tuzlu sos, bilinen malzemeler"),
    ])
    toolset, tools = toolset_for(library, settings, estimator)

    out = await tools["yenisiyle_degistir"].call(
        {"tarih": DAYS[0].isoformat(), "istek": "bu olmamış, daha yenilikçi bir şey"}
    )

    assert "Değiştirildi" in out and "Kore Usulü Bulgogi" in out and "(Kore)" in out
    main = next(i for i in session.meal_plan.items if i.date == DAYS[0] and i.meal_slot == "dinner_main")
    assert main.recipe.name == "Kore Usulü Bulgogi"
    assert main.recipe.status == RecipeStatus.CANDIDATE and len(main.recipe.ingredients) == 3
    assert toolset.touched_session_id == session.id
    prompt = estimator.prompts[0]
    assert "Fırında Tavuk" in prompt and "Karnıyarık" in prompt  # kaçınılacaklar
    assert "balık kullanma" in prompt and "daha yenilikçi" in prompt
    assert "ana yemeği" in prompt


@pytest.mark.asyncio
async def test_yenisiyle_degistir_works_on_the_weekly_meze_list(library, settings):
    RecipeService(library).upsert_recipe(
        RecipeInput(name="Haydari 2", category="meze", meal_type="dinner",
                    ingredients=[IngredientInput(name="yoğurt", quantity=1, unit="adet")])
    )
    session = plan(library, [*week_rows(), (0, "hafta_meze_1", "Haydari")])
    toolset, tools = toolset_for(library, settings, FakeEstimator([idea("Muhammara", "2 adet kırmızı biber", "1 su bardağı ceviz")]))

    out = await tools["yenisiyle_degistir"].call({"tarih": "HAFTA", "ogun_slotu": "hafta_meze_1"})

    assert "Muhammara" in out
    meze = next(i for i in session.meal_plan.items if i.meal_slot == "hafta_meze_1")
    assert meze.recipe.name == "Muhammara" and meze.recipe.category == "meze"


@pytest.mark.asyncio
async def test_yenisiyle_degistir_explains_when_nothing_fits_or_ai_is_off(library, settings):
    plan(library, week_rows())
    _, tools = toolset_for(library, settings, FakeEstimator([idea("Fırında Tavuk")]))
    assert "Uygun yeni öneri çıkmadı" in await tools["yenisiyle_degistir"].call({"tarih": DAYS[0].isoformat()})

    _, tools = toolset_for(library, settings, None)
    assert "yapay zekâ kapalı" in await tools["yenisiyle_degistir"].call({"tarih": DAYS[0].isoformat()})


def test_prompt_points_new_dish_requests_at_the_tool():
    from app.agent.prompts import SYSTEM_PROMPT

    assert "`yenisiyle_degistir`" in SYSTEM_PROMPT


# --- uygulama: Telegram yok, tarifler, yeni bir şey bul --------------------------------

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.api import create_api_app  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.planner.service import MealPlannerService  # noqa: E402
from tests.conftest import seed_recipes  # noqa: E402

TOKEN = "n" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def app_settings(settings):
    # Üretimdeki varsayılan: menü Telegram'dan gitmez.
    return settings.model_copy(update={"app_api_token": TOKEN, "telegram_menu_messages": False, "no_repeat_meals": True})


@pytest.fixture()
def factory(app_settings):
    engine = create_engine(app_settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        seed_recipes(db)
    yield Session
    engine.dispose()


class Notifier:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(chat_id)


@pytest.mark.asyncio
async def test_approving_in_the_app_does_not_send_telegram(factory, app_settings):
    with factory() as db:
        await MealPlannerService(db, app_settings).create_or_get_weekly_session(WEEK)
    notifier = Notifier()
    client = TestClient(create_api_app(app_settings, factory, agent=None, notifier=notifier))

    body = client.post("/api/v1/menu/onayla", headers=AUTH, json={"hafta": "gelecek_hafta"}).json()

    assert notifier.sent == []
    assert "Telegram" not in body["mesaj"] and "uygulamada" in body["mesaj"]
    assert body["plan"]["onaylanabilir"] is False
    approved = client.get("/api/v1/menu", headers=AUTH, params={"hafta": "gelecek_hafta"}).json()["plan"]
    assert approved["durum"].lower() in ("approved", "published")


@pytest.mark.asyncio
async def test_menu_recipes_lists_every_dish_once_with_ingredients(factory, app_settings):
    with factory() as db:
        session = await MealPlannerService(db, app_settings).create_or_get_weekly_session(WEEK)
        names = {i.recipe.name for i in session.meal_plan.items}
    client = TestClient(create_api_app(app_settings, factory, agent=None))

    body = client.get("/api/v1/menu/tarifler", headers=AUTH, params={"hafta": "gelecek_hafta", "kisi": 2}).json()

    assert body["hafta_baslangic"] == WEEK.isoformat()
    assert [r["ad"] for r in body["tarifler"]] == list(dict.fromkeys(r["ad"] for r in body["tarifler"]))
    assert {r["ad"] for r in body["tarifler"]} == names
    first = body["tarifler"][0]
    assert first["gun"] == "Pazartesi" and first["kisi"] == 2 and first["malzemeler"]
    assert client.get("/api/v1/menu/tarifler", headers=AUTH, params={"hafta": "bu_hafta"}).json()["tarifler"] == []


@pytest.mark.asyncio
async def test_app_button_puts_a_brand_new_dish_without_chat(factory, app_settings, monkeypatch):
    with factory() as db:
        RecipeService(db).upsert_recipe(
            RecipeInput(name="Karnıyarık", category="main", meal_type="dinner",
                        ingredients=[IngredientInput(name="patlıcan", quantity=1, unit="adet")])
        )
        session = await MealPlannerService(db, app_settings).create_or_get_weekly_session(WEEK)
        main = next(i for i in session.meal_plan.items if i.date == WEEK and i.meal_slot.endswith("main"))
        slot = main.meal_slot

    import app.agent.tools as tools_module

    estimator = FakeEstimator([idea("Tavuklu Pad Thai", "300 gr pirinç eriştesi", "400 gr tavuk göğsü", mutfak="Tay")])
    original = tools_module.MealAgentToolset.__init__

    def with_estimator(self, settings, session_factory, **kwargs):
        kwargs["estimator"] = estimator
        original(self, settings, session_factory, **kwargs)

    monkeypatch.setattr(tools_module.MealAgentToolset, "__init__", with_estimator)
    client = TestClient(create_api_app(app_settings, factory, agent=None))

    body = client.post("/api/v1/menu/yenisi", headers=AUTH,
                       json={"tarih": WEEK.isoformat(), "slot": slot, "hafta": "gelecek_hafta"}).json()

    monday = next(d for d in body["plan"]["gunler"] if d["tarih"] == WEEK.isoformat())
    dish = next(m for m in monday["ogunler"] if m["slot"] == slot)
    assert dish["tarif"] == "Tavuklu Pad Thai" and dish["yeni"] is True
    assert "Tavuklu Pad Thai" in body["mesaj"]
