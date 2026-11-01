"""Offline grounded-search fixtures: no live model, bot, or production DB."""
import json
import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import Recipe, RecipeStatus, SessionState, WeeklyPlanningSession
from app.memory.preferences import PreferenceService
from app.planner.research import MenuResearchError, TAG, Target, WebMenuResearch, similarity
from app.planner.service import MealPlannerService
from app.recipes.importer import RecipeInput
from app.recipes.service import RecipeService
from test_no_repeat import WEEK, plan, toolset_for

MAINS = ["Limonlu Hindi Kapama", "Nohutlu Ispanaklı Tagine", "Miso Soslu Somon", "Kuzu İncik",
         "Tofulu Sebze Güveç", "Kimyonlu Dana Köftesi", "Ispanaklı Yumurta"]
SIDES = ["Bademli Pirinç Pilavı", "Zencefilli Havuç Sote", "Buharda Susamlı Brokoli", "Limonlu Patates Püresi",
         "Domatesli Kuskus", "Naneli Sebze Çorbası", "Fırınlanmış Renkli Biber"]
MEZES = ["Cevizli Kabak Tarator", "Avokadolu Humus", "Pancarlı Haydari", "Fesleğenli Biber Ezmesi"]


class FakeWeb:
    def __init__(self, *, bad_source=False, bad_main=False, absent_names=False, failure=False):
        self.searches, self.structured = [], []
        self.rows = []
        self.bad_source, self.bad_main = bad_source, bad_main
        self.absent_names, self.failure = absent_names, failure

    async def search_text(self, prompt):
        self.searches.append(prompt)
        if self.failure:
            raise RuntimeError("temporary provider error")
        targets = re.findall(r"^(\d+)\) (\d{4}-\d{2}-\d{2}): ([^,]+), rol=(\w+);", prompt, re.M)
        self.rows = []
        for number, day, slot, role in targets:
            day_index = (WEEK.fromisoformat(day) - WEEK).days % 7
            name = (MAINS if role == "main" else SIDES)[day_index]
            if role in {"meze", "salad"}:
                name = MEZES[(int(slot.rsplit("_", 1)[-1]) - 1) % len(MEZES)]
            if self.bad_main and role == "main":
                name = "Zerdeçallı Siyez Pilavı"
            url = f"https://recipes.example/{day}/{slot}"
            self.rows.append({"icin": int(number), "ad": name, "kategori": role,
                              "kaynak": "https://invented.example/fake" if self.bad_source else url,
                              "malzemeler": ["600 g hindi eti" if role == "main" else "200 g havuç", "2 adet soğan"],
                              "hazirlanis": "Malzemeleri hazırlayın. Tencerede pişirip sıcak servis edin.",
                              "neden": "Farklı pişirme yöntemi ve o günün ana yemeğiyle uyumlu lezzetler.",
                              "porsiyon": 4, "kcal": 200, "protein_g": 20})
        text = "Tarif bulunamadı." if self.absent_names else json.dumps(self.rows, ensure_ascii=False)
        return text, [f"Örnek Tarif: https://recipes.example/{day}/{slot}" for _, day, slot, _ in targets]

    async def ask_json(self, prompt, schema):
        self.structured.append(prompt)
        return json.dumps({"tarifler": self.rows})

    async def fill_missing(self, db, recipes):
        return []


def configured(settings):
    return settings.model_copy(update={"menu_research_enabled": True, "weekly_meze_count": 4})


def researcher(settings, fake):
    return WebMenuResearch(settings, fake.search_text, fake.ask_json)


def test_production_default_is_web_research():
    assert Settings(_env_file=None).menu_research_enabled is True


@pytest.mark.asyncio
async def test_entire_week_is_researched_main_first_and_no_library_is_selected(db, settings):
    settings = configured(settings)
    old_ids = set(db.scalars(select(Recipe.id)))
    fake = FakeWeb()
    session = await MealPlannerService(db, settings, researcher(settings, fake)).create_or_get_weekly_session(WEEK)
    assert len(fake.searches) == 2
    assert "rol=main" in fake.searches[0] and "rol=side" not in fake.searches[0]
    assert MAINS[0] in fake.searches[1]  # side research sees the selected day's main
    assert {i.recipe_id for i in session.meal_plan.items}.isdisjoint(old_ids)
    assert len(session.meal_plan.items) == 18
    assert all(i.recipe.status == RecipeStatus.CANDIDATE for i in session.meal_plan.items)
    assert all(TAG in i.recipe.tags and i.recipe.source.startswith("https://recipes.example/") for i in session.meal_plan.items)
    assert all(i.recipe.notes for i in session.meal_plan.items)
    assert session.state == SessionState.AWAITING_ADMIN_FEEDBACK


@pytest.mark.parametrize("options", [{"bad_source": True}, {"bad_main": True}, {"absent_names": True}, {"failure": True}])
@pytest.mark.asyncio
async def test_bad_or_missing_search_never_saves_a_menu_or_falls_back(db, settings, options):
    settings = configured(settings)
    original_count = db.scalar(select(func.count()).select_from(Recipe))
    with pytest.raises(MenuResearchError):
        await MealPlannerService(db, settings, researcher(settings, FakeWeb(**options))).create_or_get_weekly_session(WEEK)
    assert db.scalar(select(func.count()).select_from(Recipe)) == original_count
    assert db.scalar(select(WeeklyPlanningSession)) is None


@pytest.mark.asyncio
async def test_unconfigured_search_explains_instead_of_using_library(db, settings):
    with pytest.raises(MenuResearchError, match="eski tariflerle menü doldurulmadı"):
        await MealPlannerService(db, configured(settings)).create_or_get_weekly_session(WEEK)


@pytest.mark.asyncio
async def test_failed_regeneration_preserves_old_draft_and_rolls_back_candidates(db, settings):
    old = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    old_items = [(i.id, i.recipe_id) for i in old.meal_plan.items]
    count = db.scalar(select(func.count()).select_from(Recipe))
    PreferenceService(db).add("Kişi başı öğün en fazla 100 kcal")
    new = configured(settings)
    with pytest.raises(ValueError):
        await MealPlannerService(db, new, researcher(new, FakeWeb())).create_or_get_weekly_session(WEEK, regenerate=True)
    assert [(i.id, i.recipe_id) for i in old.meal_plan.items] == old_items
    assert db.scalar(select(func.count()).select_from(Recipe)) == count


@pytest.mark.asyncio
async def test_preparation_returns_sources_and_reason_without_changing_menu(db, settings):
    toolset, tools = toolset_for(db, configured(settings), FakeWeb())
    text = await tools["plan_hazirla"].call({"istek": "bu hafta daha hafif olsun"})
    assert "İNTERNETTEN YENİ ARAŞTIRMA" in text, text
    assert "Kaynak: https://recipes.example/" in text and "Neden:" in text
    assert db.scalar(select(WeeklyPlanningSession)) is None
    assert toolset.estimator.searches[0].find("bu hafta daha hafif olsun") >= 0


@pytest.mark.asyncio
async def test_agent_cannot_silently_build_new_menu_from_old_recipes(db, settings):
    _, tools = toolset_for(db, configured(settings), FakeWeb())
    text = await tools["plan_kaydet"].call({"ogunler": [f"{WEEK}|dinner_main|Fırında Tavuk"]})
    assert "Plan kaydedilmedi" in text and "internetten araştırılmış" in text
    assert db.scalar(select(WeeklyPlanningSession)) is None
    explicit = await tools["plan_kaydet"].call({"ogunler": [f"{WEEK}|dinner_main|Fırında Tavuk"], "kutuphaneden": True})
    assert "kaydedildi" in explicit


@pytest.mark.asyncio
async def test_prepared_web_recipes_can_be_saved_by_agent(db, settings):
    _, tools = toolset_for(db, configured(settings), FakeWeb())
    text = await tools["plan_hazirla"].call({})
    lines = [line for line in text.splitlines() if line.count("|") == 2]
    assert len(lines) == 18, text
    saved = await tools["plan_kaydet"].call({"ogunler": lines})
    assert "kaydedildi" in saved, saved
    assert all(TAG in i.recipe.tags for i in db.scalar(select(WeeklyPlanningSession)).meal_plan.items)


@pytest.mark.asyncio
async def test_final_menu_is_protected_before_search(db, settings):
    session = plan(db, [(0, "dinner_main", "Fırında Tavuk")])
    session.state = SessionState.APPROVED
    db.commit()
    fake = FakeWeb()
    with pytest.raises(ValueError, match="approved"):
        await MealPlannerService(db, configured(settings), researcher(configured(settings), fake)).create_or_get_weekly_session(WEEK, regenerate=True)
    assert fake.searches == []


def test_same_protein_is_allowed_but_another_sauce_is_not_new():
    old = RecipeInput(name="Fırında Tavuk", protein_type="chicken")
    sauce = RecipeInput(name="Limon Soslu Fırında Tavuk", protein_type="chicken")
    different = RecipeInput(name="Kore Usulü Tavuk Sote", protein_type="chicken")
    assert similarity(sauce, old) >= 0.8
    assert similarity(different, old) < 0.8
