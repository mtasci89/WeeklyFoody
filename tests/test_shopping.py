from __future__ import annotations

from datetime import date, timedelta

from app.db.models import MealPlan, MealPlanItem, PantryItem, SessionState, WeeklyPlanningSession
from app.recipes.service import RecipeService
from app.shopping.aggregator import ShoppingAggregator, ShoppingIngredient
from app.shopping.service import ShoppingListService


def make_plan(db, recipe_names: list[str]) -> MealPlan:
    session = WeeklyPlanningSession(week_start=date(2026, 8, 31), week_end=date(2026, 9, 6), state=SessionState.APPROVED)
    plan = MealPlan(session=session, status="final")
    for idx, name in enumerate(recipe_names):
        recipe = RecipeService(db).find_recipe(name)
        plan.items.append(MealPlanItem(date=date(2026, 8, 31) + timedelta(days=idx), meal_slot="dinner", recipe_id=recipe.id))
    db.add(session)
    db.commit()
    return plan


def test_shopping_aggregates_and_converts_g_to_kg(db, settings):
    plan = make_plan(db, ["Fırında Tavuk", "Fırında Tavuk"])
    items = ShoppingListService(db, settings).generate(plan)
    chicken = next(item for item in items if item.name == "tavuk")
    assert chicken.quantity == 2000
    assert chicken.unit == "g"
    assert chicken.format() == "2 kg tavuk"


def test_shopping_scales_servings(db, settings):
    plan = make_plan(db, ["Fırında Tavuk"])
    plan.items[0].servings = 6
    db.commit()
    chicken = next(item for item in ShoppingListService(db, settings).generate(plan) if item.name == "tavuk")
    assert chicken.quantity == 1500


def test_incompatible_units_are_not_combined():
    items = ShoppingAggregator().aggregate(
        [
            ShoppingIngredient("soğan", 1, "adet", "Sebze & Meyve"),
            ShoppingIngredient("soğan", 50, "g", "Sebze & Meyve"),
        ]
    )
    assert len(items) == 2


def test_pantry_items_are_excluded(db, settings):
    db.add(PantryItem(ingredient_name="patates"))
    db.commit()
    plan = make_plan(db, ["Fırında Tavuk"])
    names = {item.name for item in ShoppingListService(db, settings).generate(plan)}
    assert "patates" not in names
