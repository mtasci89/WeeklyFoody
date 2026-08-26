from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db.models import MealPlan, MealPlanItem, PreferenceType, SessionState, WeeklyPlanningSession
from app.memory.preferences import PreferenceService
from app.planner.candidate_selector import CandidateSelector
from app.planner.revision import RevisionService
from app.planner.service import MealPlannerService
from app.recipes.service import RecipeService


@pytest.mark.asyncio
async def test_planner_does_not_violate_hard_preferences(db, settings):
    PreferenceService(db).add("Bundan sonra tavuk önerme.", PreferenceType.HARD)
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(date(2026, 8, 31))
    names = [item.recipe.name.casefold() for item in session.meal_plan.items]
    assert all("tavuk" not in name for name in names)


def test_candidate_selector_reduces_recent_repetition(db):
    recipes = RecipeService(db).list_recipes()
    chicken = RecipeService(db).find_recipe("Fırında Tavuk")
    previous = WeeklyPlanningSession(week_start=date(2026, 8, 24), week_end=date(2026, 8, 30), state=SessionState.PUBLISHED)
    plan = MealPlan(session=previous, status="final")
    plan.items.append(MealPlanItem(date=date(2026, 8, 24), meal_slot="dinner", recipe_id=chicken.id))
    db.add(previous)
    db.commit()

    selected = CandidateSelector(db).select("dinner", [], date(2026, 8, 31), recent_weeks=3)
    assert chicken.id not in {recipe.id for recipe in selected}
    assert len(selected) == len(recipes) - 1


@pytest.mark.asyncio
async def test_weekly_session_is_idempotent(db, settings):
    service = MealPlannerService(db, settings)
    first = await service.create_or_get_weekly_session(date(2026, 8, 31))
    second = await service.create_or_get_weekly_session(date(2026, 8, 31))
    assert first.id == second.id


@pytest.mark.asyncio
async def test_planner_creates_multiple_dishes_per_day(db, settings):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(date(2026, 8, 31))
    assert len(session.meal_plan.items) == 7 * settings.courses_per_day
    monday_items = [item for item in session.meal_plan.items if item.date == date(2026, 8, 31)]
    assert len(monday_items) == settings.courses_per_day


@pytest.mark.asyncio
async def test_revision_keeps_untouched_meals(db, settings):
    service = MealPlannerService(db, settings)
    session = await service.create_or_get_weekly_session(date(2026, 8, 31))
    before = {(item.date, item.meal_slot): item.recipe.name for item in session.meal_plan.items}

    revised = await RevisionService(db, settings).revise(session, "Çarşambaya Kuru Fasulye koy.")
    after = {(item.date, item.meal_slot): item.recipe.name for item in revised.meal_plan.items}

    target = date(2026, 9, 2)
    changed = [key for key, recipe_name in after.items() if key[0] == target and recipe_name == "Kuru Fasulye" and before[key] != recipe_name]
    assert len(changed) <= 1
    assert any(recipe_name == "Kuru Fasulye" for key, recipe_name in after.items() if key[0] == target)
    for key, recipe_name in before.items():
        if key[0] != target:
            assert after[key] == recipe_name


@pytest.mark.asyncio
async def test_revision_changes_only_matching_food_within_day(db, settings):
    service = MealPlannerService(db, settings)
    session = await service.create_or_get_weekly_session(date(2026, 8, 31))
    fish = RecipeService(db).find_recipe("Izgara Balık")
    pasta = RecipeService(db).find_recipe("Makarna")
    tuesday_items = [item for item in session.meal_plan.items if item.date == date(2026, 9, 1)]
    for item in tuesday_items:
        item.recipe_id = pasta.id
        item.recipe = pasta
    first_tuesday = tuesday_items[0]
    first_tuesday.recipe_id = fish.id
    first_tuesday.recipe = fish
    db.commit()
    before = {(item.date, item.meal_slot): item.recipe.name for item in session.meal_plan.items}

    revised = await RevisionService(db, settings).revise(session, "Salıdaki balığı çıkar.")
    after = {(item.date, item.meal_slot): item.recipe.name for item in revised.meal_plan.items}

    changed = [key for key in before if before[key] != after[key]]
    assert changed == [(date(2026, 9, 1), first_tuesday.meal_slot)]
    assert "Balık" not in after[changed[0]]


def test_excluded_inactive_recipes_are_not_candidates(db):
    RecipeService(db).disable_recipe("Makarna")
    selected = CandidateSelector(db).select("dinner", [], date(2026, 8, 31), recent_weeks=3)
    assert "Makarna" not in {recipe.name for recipe in selected}
