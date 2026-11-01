"""Mislabelled discovered/generated garnishes must never become main courses."""
from datetime import date

import pytest

from app.agent.daily_discovery import discover_daily
from app.db.models import Recipe, RecipeStatus
from app.memory.rules import RuleViolation, validate_session
from app.planner.candidate_selector import CandidateSelector
from app.planner.service import MealPlannerService
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.roles import matches_course_role, recipe_category
from app.recipes.service import RecipeService
from test_daily_discovery import FakeGemini, TODAY, recipe
from test_no_repeat import DAYS, FakeEstimator, idea, plan, toolset_for


@pytest.mark.parametrize(("name", "category"), [
    ("Zerdeçallı Siyez Pilavı", "side"),
    ("Tavuk Suyuna Bulgur Pilavı", "side"),
    ("Fesleğenli ve Limonlu Risotto", "side"),
    ("Tavuklu Makarna", "side"),
    ("Köz Patlıcan Salatası", "salad"),
    ("Kinoa Krutonlu ve Fesleğenli Salata", "salad"),
    ("Tavuklu Sezar Salata", "salad"),
    ("Kırmızı Mercimek Köftesi", "meze"),
    ("Közlenmiş Kırmızı Biber Ezmesi", "meze"),
    ("Közlenmiş Kırmızı Biber", "side"),
    ("Mantar Sote", "side"),
    ("Mantar Stroganoff", "side"),
    ("MANTAR SOTE", "side"),
    ("Mantar Çorbası", "soup"),
    ("Peynirli Fırın Mantar", "side"),
    ("Zencefilli Havuç Sote", "side"),
    ("Fırınlanmış Tatlı Patates Çubukları", "side"),
])
def test_dish_form_overrides_incorrect_main_label(name, category):
    row = RecipeInput(name=name, category="main", protein_type="beef")  # untrusted metadata
    assert recipe_category(row) == category
    assert not matches_course_role(row, "main")


@pytest.mark.parametrize("name", [
    "Kuzu Eti Söğüş", "Hindi Tandır", "Fırında Çipura", "Izgara Köfte",
    "Kuru Fasulye", "Nohutlu Ispanaklı Tagine", "Menemen", "Tofu Güveç",
    "Mantarlı Tavuk Sote", "Mantar Soslu Dana Bonfile", "Etli Patlıcan Sote",
])
def test_real_main_dishes_remain_available(name):
    assert matches_course_role(RecipeInput(name=name), "main")


def test_ingredients_distinguish_mushroom_garnish_from_meat_main():
    def row(ingredient):
        return RecipeInput(name="Mantarlı Güveç", ingredients=[IngredientInput(name=ingredient, quantity=600, unit="g")])
    assert matches_course_role(row("tavuk göğsü"), "main")
    assert not matches_course_role(row("tavuk suyu"), "main")
    assert not matches_course_role(row("parmesan peyniri"), "main")
    fancy = RecipeInput(name="Kremalı Orman Lezzeti", ingredients=[IngredientInput(name="istiridye mantarı")])
    assert not matches_course_role(fancy, "main")


def test_old_incorrect_labels_are_filtered_without_rewriting_db(db):
    old = Recipe(name="Safranlı Pirinç Pilavı", category="main", meal_type="dinner", status=RecipeStatus.APPROVED)
    db.add(old)
    db.commit()
    selector = CandidateSelector(db)
    assert old not in selector.select("dinner", [], date(2026, 11, 2), course_role="main")
    assert old in selector.select("dinner", [], date(2026, 11, 2), course_role="side")
    assert old.category == "main"  # no migration or silent user-data edits


@pytest.mark.asyncio
async def test_daily_discovery_corrects_wrong_category_before_saving(db):
    gemini = FakeGemini([[recipe("Zerdeçallı Siyez Pilavı"), recipe("Köz Patlıcan Salatası"), recipe("Mantar Sote")]])
    names = await discover_daily(db, gemini.search, gemini.ask_json, count=3, today=TODAY)
    assert len(names) == 3
    assert [RecipeService(db).find_recipe(name).category for name in names] == ["side", "salad", "side"]


@pytest.mark.asyncio
async def test_fresh_main_ignores_all_garnishes_and_chooses_real_main(db, settings):
    session = plan(db, [(0, "dinner_main", "Fırında Tavuk")])
    estimator = FakeEstimator([
        idea("Zerdeçallı Siyez Pilavı"), idea("Mantar Stroganoff"), idea("Köz Patlıcan Salatası"),
        idea("Baharatlı Hindi Tandır", "600 g hindi but", "1 adet soğan"),
    ])
    _, tools = toolset_for(db, settings, estimator)
    result = await tools["yenisiyle_degistir"].call({"ogunler": [f"{DAYS[0]}|dinner_main"]})
    assert "Fırında Tavuk → Baharatlı Hindi Tandır" in result
    assert session.meal_plan.items[0].recipe.name == "Baharatlı Hindi Tandır"
    assert RecipeService(db).find_recipe("Mantar Stroganoff") is None


@pytest.mark.asyncio
async def test_bad_fresh_suggestions_leave_plan_unchanged(db, settings):
    session = plan(db, [(0, "dinner_main", "Fırında Tavuk")])
    _, tools = toolset_for(db, settings, FakeEstimator([idea("Mantar Sote"), idea("Siyez Pilavı")]))
    result = await tools["yenisiyle_degistir"].call({"ogunler": [f"{DAYS[0]}|dinner_main"]})
    assert "uygun yeni öneri çıkmadı" in result
    assert session.meal_plan.items[0].recipe.name == "Fırında Tavuk"


@pytest.mark.asyncio
async def test_direct_swap_cannot_bypass_main_role(db, settings):
    session = plan(db, [(0, "dinner_main", "Fırında Tavuk")])
    _, tools = toolset_for(db, settings)
    result = await tools["ogun_degistir"].call({"tarih": str(DAYS[0]), "yeni_tarif": "Makarna", "ogun_slotu": "dinner_main", "gerekce": "test"})
    assert "kaydedilmedi" in result
    assert session.meal_plan.items[0].recipe.name == "Fırında Tavuk"


@pytest.mark.asyncio
async def test_invalid_old_plan_can_be_fixed_one_main_at_a_time(db, settings):
    service = RecipeService(db)
    service.upsert_recipe(RecipeInput(name="Mantar Sote"))
    service.upsert_recipe(RecipeInput(name="Siyez Pilavı"))
    session = plan(db, [(0, "dinner_main", "Mantar Sote"), (1, "dinner_main", "Siyez Pilavı")])
    _, tools = toolset_for(db, settings)
    result = await tools["ogun_degistir"].call({"tarih": str(DAYS[0]), "yeni_tarif": "Izgara Köfte", "ogun_slotu": "dinner_main", "gerekce": "test"})
    assert result.startswith("Değiştirildi")
    with pytest.raises(RuleViolation, match="ana yemek olamaz"):
        validate_session(db, session, settings)  # remaining invalid main cannot be approved


@pytest.mark.asyncio
async def test_empty_main_pool_never_falls_back_to_sides(db, settings):
    for row in RecipeService(db).list_recipes():
        if matches_course_role(row, "main"):
            row.status = RecipeStatus.INACTIVE
    db.commit()
    with pytest.raises(ValueError, match="dinner_main için uygun tarif yok"):
        await MealPlannerService(db, settings)._generate_structured_plan(date(2026, 11, 2))
