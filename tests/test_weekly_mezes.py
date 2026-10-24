"""Mezeler günlere bölünmez: haftalık ayrı bir liste.

Kullanıcı: "mezeleri öğünlere ekleme", "mezeler günlere bölünmesin dedim ama hâlâ
günlere ayrışmış". Ayrıca asistan haftayı baştan yazmadan yemek ekleyip
çıkarabilmeli ve ekranda bakılan haftayı değiştirmeli.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.prompts import context_block
from app.agent.tools import MealAgentToolset
from app.api import create_api_app, menu_json
from app.config import is_weekly_slot
from app.db.models import Base
from app.formatting import calorie_summary, format_meal_plan
from app.memory.preferences import PreferenceService
from app.memory.rules import MealRules, RuleViolation
from app.planner.dates import next_week_start, this_week_start
from app.planner.service import MealPlannerService
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.nutrition import NutritionInput, save_nutrition
from app.recipes.service import RecipeService
from tests.conftest import seed_recipes

WEEK = next_week_start(timezone="Europe/Istanbul")
TOKEN = "m" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
MEZELER = ["Atom", "Muhammara", "Fava", "Patlıcan Ezmesi", "Cacık"]


def add_mezes(db):
    service = RecipeService(db)
    for name in MEZELER:
        service.upsert_recipe(
            RecipeInput(
                name=name, category="meze", meal_type="dinner", servings=4, vegetarian=True,
                ingredients=[IngredientInput(name=f"{name} malzemesi", quantity=1, unit="adet")],
            )
        )


@pytest.fixture()
def wsettings(settings):
    """Kullanıcının istediği varsayılan: haftada 4 meze, günlere bölünmez."""
    return settings.model_copy(update={"weekly_meze_count": 4, "app_api_token": TOKEN})


@pytest.fixture()
def wdb(db):
    add_mezes(db)
    return db


@pytest.fixture()
def tools(wdb, wsettings):
    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return wdb

        def __exit__(self, *exc):
            return False

    toolset = MealAgentToolset(wsettings, _Factory())
    return toolset, {t.name: t for t in toolset.build()}


async def call(tools, name, **kwargs):
    return await tools[1][name].call(kwargs)


async def weekly_plan(db, settings, week=WEEK):
    return await MealPlannerService(db, settings).create_or_get_weekly_session(week)


# --- kural -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("Mezeler günlere bölünmesin", -1),
        ("mezeler günlere bölünmesin, haftalık ayrı liste olsun", -1),
        ("Mezeler haftalık olsun", -1),
        ("Haftada 4 meze olsun", 4),
        ("haftalık üç meze", 3),
        ("Mezeler günlere dağıtılsın", 0),
    ],
)
def test_weekly_meze_rules_are_understood(rule, expected):
    rules = MealRules.parse([rule])
    assert rules.weekly_mezes == expected
    assert not rules.advisory and not rules.excluded


def test_meze_target_comes_from_rule_or_setting(wsettings):
    assert MealRules().weekly_meze_target(wsettings) == 4
    assert MealRules.parse(["haftada 3 meze"]).weekly_meze_target(wsettings) == 3
    assert MealRules.parse(["mezeler günlere dağıtılsın"]).weekly_meze_target(wsettings) == 0
    off = wsettings.model_copy(update={"weekly_meze_count": 0})
    assert MealRules.parse(["mezeler günlere bölünmesin"]).weekly_meze_target(off) == 4
    with pytest.raises(RuleViolation):
        MealRules.parse(["haftada 40 meze olsun"])


def test_weekly_mode_drops_mezes_from_the_daily_shape(wsettings):
    slots = MealRules().settings_for_plan(wsettings).planning_slots
    assert slots == ["dinner_main", "dinner_side"]
    legacy = wsettings.model_copy(update={"weekly_meze_count": 0})
    assert "dinner_meze_1" in MealRules().settings_for_plan(legacy).planning_slots


# --- otomatik plan -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_automatic_plan_has_a_weekly_meze_list_and_no_daily_mezes(wdb, wsettings):
    session = await weekly_plan(wdb, wsettings)
    items = session.meal_plan.items
    weekly = [i for i in items if is_weekly_slot(i.meal_slot)]
    daily = [i for i in items if not is_weekly_slot(i.meal_slot)]

    assert len(weekly) == 4
    assert len({i.recipe_id for i in weekly}) == 4
    assert all(i.recipe.category == "meze" for i in weekly)  # asıl mezeler önce
    assert all(i.date == WEEK for i in weekly)
    assert not [i for i in daily if i.recipe.category in ("meze", "salad")]
    assert len(daily) == 7 * 2


@pytest.mark.asyncio
async def test_weekly_mezes_respect_exclusions_and_stay_out_of_daily_calories(wdb, wsettings):
    PreferenceService(wdb).add("Atom kullanma")
    for recipe in RecipeService(wdb).list_recipes():
        save_nutrition(wdb, recipe, NutritionInput(calories_kcal=100, source="test"))
    PreferenceService(wdb).add("Kalorileri yaz")
    session = await weekly_plan(wdb, wsettings)

    assert "Atom" not in {i.recipe.name for i in session.meal_plan.items}
    summary = calorie_summary(session)
    assert "haftalık mezeler hariç" in summary
    assert "~200 kcal" in summary  # ana + yan; mezeler güne sayılmaz
    plan = menu_json(wdb, session, wsettings)["plan"]
    assert all(day["toplam_kcal"] == 200 for day in plan["gunler"])
    assert len(plan["mezeler"]) == 4
    assert all(m["rol"] == "Meze" for m in plan["mezeler"])
    text = format_meal_plan(session)
    assert "*Haftanın mezeleri*" in text


@pytest.mark.asyncio
async def test_rule_switches_back_to_daily_mezes(wdb, wsettings):
    PreferenceService(wdb).add("Mezeler günlere dağıtılsın")
    session = await weekly_plan(wdb, wsettings)
    assert not [i for i in session.meal_plan.items if is_weekly_slot(i.meal_slot)]
    assert any(i.meal_slot.startswith("dinner_meze") for i in session.meal_plan.items)


# --- ajan araçları ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_hazirla_explains_the_weekly_meze_list(tools):
    out = await call(tools, "plan_hazirla")
    assert "MEZELER GÜNLERE BÖLÜNMEZ" in out and "HAFTA|hafta_meze_1|" in out
    assert "dinner_meze" not in out.split("Önerilen gün şekli")[1].split("\n")[0]


@pytest.mark.asyncio
async def test_plan_kaydet_takes_weekly_lines_and_refuses_daily_mezes(wdb, wsettings, tools):
    days = [WEEK.fromordinal(WEEK.toordinal() + k).isoformat() for k in range(7)]
    lines = [f"{d}|dinner_main|Fırında Tavuk" if k % 2 else f"{d}|dinner_main|Kuru Fasulye" for k, d in enumerate(days)]
    bad = lines + [f"{days[0]}|dinner_meze|Haydari"]
    out = await call(tools, "plan_kaydet", ogunler=bad)
    assert "Plan kaydedilmedi" in out and "günlere bölünmüyor" in out

    good = lines + ["HAFTA|hafta_meze_1|Haydari", "HAFTA|hafta_meze_2|Atom"]
    out = await call(tools, "plan_kaydet", ogunler=good)
    assert "kaydedildi" in out and "Haftanın mezeleri: 2 (hedef 4)" in out
    assert "HAFTANIN MEZELERİ" in out
    session = MealPlannerService(wdb, wsettings).current_session(WEEK)
    weekly = sorted((i.meal_slot, i.recipe.name) for i in session.meal_plan.items if is_weekly_slot(i.meal_slot))
    assert weekly == [("hafta_meze_1", "Haydari"), ("hafta_meze_2", "Atom")]


@pytest.mark.asyncio
async def test_ogun_ekle_adds_without_touching_other_meals(wdb, wsettings, tools):
    session = await weekly_plan(wdb, wsettings)
    before = {(i.date, i.meal_slot): i.recipe.name for i in session.meal_plan.items}

    out = await call(tools, "ogun_ekle", tarih=WEEK.isoformat(), tarif="Mercimek Çorbası")
    assert out.startswith("Eklendi")
    after = {(i.date, i.meal_slot): i.recipe.name for i in session.meal_plan.items}
    added = set(after) - set(before)
    assert len(added) == 1 and after[added.pop()] == "Mercimek Çorbası"
    assert all(after[k] == v for k, v in before.items())
    assert tools[0].touched_session_id == session.id

    again = await call(tools, "ogun_ekle", tarih=WEEK.isoformat(), tarif="Mercimek Çorbası")
    assert "zaten var" in again


@pytest.mark.asyncio
async def test_a_meze_asked_for_a_day_goes_to_the_weekly_list(wdb, wsettings, tools):
    session = await weekly_plan(wdb, wsettings)
    free = next(name for name in ["Cacık", "Fava", "Patlıcan Ezmesi", "Muhammara", "Atom"]
                if name not in {i.recipe.name for i in session.meal_plan.items})

    out = await call(tools, "ogun_ekle", tarih=WEEK.isoformat(), tarif=free)

    assert "günlere bölünmüyor" in out
    weekly = [i.recipe.name for i in session.meal_plan.items if is_weekly_slot(i.meal_slot)]
    assert free in weekly and len(weekly) == 5
    assert free not in [i.recipe.name for i in session.meal_plan.items if not is_weekly_slot(i.meal_slot)]


@pytest.mark.asyncio
async def test_ogun_cikar_and_degistir_work_on_the_weekly_list(wdb, wsettings, tools):
    session = await weekly_plan(wdb, wsettings)
    weekly = [i for i in session.meal_plan.items if is_weekly_slot(i.meal_slot)]
    first, second = weekly[0].recipe.name, weekly[1].recipe.name
    spare = next(n for n in MEZELER if n not in {i.recipe.name for i in weekly})

    out = await call(tools, "ogun_cikar", tarih="HAFTA", tarif_veya_slot=first, gerekce="olmamış")
    assert out.startswith("Çıkarıldı")
    out = await call(tools, "ogun_degistir", tarih="HAFTA", yeni_tarif=spare, gerekce="yenisi",
                     ogun_slotu=weekly[1].meal_slot)
    assert "Değiştirildi" in out
    names = [i.recipe.name for i in session.meal_plan.items if is_weekly_slot(i.meal_slot)]
    assert first not in names and second not in names and spare in names and len(names) == 3


@pytest.mark.asyncio
async def test_tools_change_the_week_they_are_told(wdb, wsettings, tools):
    """Eskiden araçlar hep "aktif" haftayı değiştiriyordu; ekrandaki hafta başkaysa
    değişiklik görünmüyordu."""
    this_week = this_week_start(timezone="Europe/Istanbul")
    current = await weekly_plan(wdb, wsettings, this_week)
    upcoming = await weekly_plan(wdb, wsettings)
    target = next(i for i in current.meal_plan.items if i.date == this_week and i.meal_slot == "dinner_main")
    other = "Nohut" if target.recipe.name != "Nohut" else "Kuru Fasulye"

    out = await call(tools, "ogun_degistir", tarih=this_week.isoformat(), yeni_tarif=other, gerekce="x",
                     ogun_slotu="dinner_main", hafta="bu_hafta")

    assert "Değiştirildi" in out
    assert target.recipe.name == other
    assert tools[0].touched_session_id == current.id != upcoming.id


@pytest.mark.asyncio
async def test_approved_plans_cannot_be_edited(wdb, wsettings, tools):
    session = await weekly_plan(wdb, wsettings)
    MealPlannerService(wdb, wsettings).approve(session)
    out = await call(tools, "ogun_ekle", tarih=WEEK.isoformat(), tarif="Mercimek Çorbası")
    assert "onaylanmış" in out


def test_app_channel_tells_the_agent_not_to_retype_the_menu():
    from datetime import date

    block = context_block(date(2026, 10, 24), "", [], [], [], channel="uygulama")
    assert "TEKRAR YAZMA" in block
    assert "Kanal" not in context_block(date(2026, 10, 24), "", [], [], [])


# --- uygulama API ------------------------------------------------------------------


@pytest.fixture()
def factory(wsettings):
    engine = create_engine(wsettings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        seed_recipes(db)
        add_mezes(db)
    yield Session
    engine.dispose()


class EditingAgent:
    """Gerçek araçlarla menüyü değiştiren sahte asistan."""

    def __init__(self, settings, factory):
        self.settings, self.factory = settings, factory
        self.channels: list[str] = []

        class Store:
            def history(self, chat_id):
                return []

        self.store = Store()

    async def reply(self, chat_id, message, images=None, timeout=None, channel="telegram"):
        self.channels.append(channel)
        toolset = MealAgentToolset(self.settings, self.factory)
        tools = {t.name: t for t in toolset.build()}
        await tools["ogun_ekle"].call({"tarih": WEEK.isoformat(), "tarif": "Mercimek Çorbası"})

        class Reply:
            text = "Pazartesi'ye çorba ekledim."
            ok = True
            tool_calls = toolset.calls
            plan_session_id = toolset.touched_session_id

        return Reply()


@pytest.mark.asyncio
async def test_chat_answer_carries_the_menu_and_what_changed(factory, wsettings):
    with factory() as db:
        await weekly_plan(db, wsettings)
    agent = EditingAgent(wsettings, factory)
    client = TestClient(create_api_app(wsettings, factory, agent=agent))

    body = client.post("/api/v1/sohbet", headers=AUTH, json={"mesaj": "pazartesiye çorba ekle"}).json()

    assert agent.channels == ["uygulama"]
    assert body["plan_degisti"] is True
    assert body["menu"]["plan"]["mezeler"]
    assert body["degisiklikler"] == [
        {"tarih": WEEK.isoformat(), "slot": "dinner_soup", "eski": None, "yeni": "Mercimek Çorbası"}
    ]


@pytest.mark.asyncio
async def test_app_can_add_and_remove_dishes_directly(factory, wsettings):
    with factory() as db:
        session = await weekly_plan(db, wsettings)
        meze = next(i for i in session.meal_plan.items if is_weekly_slot(i.meal_slot))
        slot, name = meze.meal_slot, meze.recipe.name
    client = TestClient(create_api_app(wsettings, factory, agent=None))

    removed = client.post("/api/v1/menu/cikar", headers=AUTH, json={"tarih": "HAFTA", "slot": slot})
    assert removed.status_code == 200
    assert name not in [m["tarif"] for m in removed.json()["plan"]["mezeler"]]

    added = client.post("/api/v1/menu/ekle", headers=AUTH, json={"tarih": "HAFTA", "tarif": name})
    assert added.status_code == 200
    assert name in [m["tarif"] for m in added.json()["plan"]["mezeler"]]

    unknown = client.post("/api/v1/menu/ekle", headers=AUTH, json={"tarih": "HAFTA", "tarif": "Uydurma"})
    assert unknown.status_code == 422 and "kütüphanede yok" in unknown.json()["detail"]


@pytest.mark.asyncio
async def test_a_date_alone_picks_the_week_it_belongs_to(wdb, wsettings, tools):
    this_week = this_week_start(timezone="Europe/Istanbul")
    current = await weekly_plan(wdb, wsettings, this_week)
    await weekly_plan(wdb, wsettings)  # gelecek hafta taslağı "aktif" olur

    out = await call(tools, "ogun_ekle", tarih=this_week.isoformat(), tarif="Mercimek Çorbası")

    assert out.startswith("Eklendi")
    assert tools[0].touched_session_id == current.id


@pytest.mark.asyncio
async def test_app_sections_draft_and_approved(factory, wsettings):
    """Uygulamanın Menü sekmesi: "Taslak" onay bekleyen planı, "Onaylı menü" onaylıyı gösterir."""
    this_week = this_week_start(timezone="Europe/Istanbul")
    with factory() as db:
        current = await weekly_plan(db, wsettings, this_week)
        MealPlannerService(db, wsettings).approve(current)
        upcoming = await weekly_plan(db, wsettings)
        current_id, upcoming_id = current.id, upcoming.id
    client = TestClient(create_api_app(wsettings, factory, agent=None))

    draft = client.get("/api/v1/menu", headers=AUTH, params={"hafta": "taslak"}).json()["plan"]
    approved = client.get("/api/v1/menu", headers=AUTH, params={"hafta": "onayli"}).json()["plan"]
    assert draft["id"] == upcoming_id and draft["onaylanabilir"] is True
    assert approved["id"] == current_id and approved["onaylanabilir"] is False

    client.post("/api/v1/menu/onayla", headers=AUTH, json={"hafta": "taslak"})
    assert client.get("/api/v1/menu", headers=AUTH, params={"hafta": "taslak"}).json()["plan"] is None
