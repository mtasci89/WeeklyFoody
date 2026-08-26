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
async def test_revision_keeps_untouched_meals(db, settings):
    service = MealPlannerService(db, settings)
    session = await service.create_or_get_weekly_session(date(2026, 8, 31))
    before = {item.date: item.recipe.name for item in session.meal_plan.items}

    revised = await RevisionService(db, settings).revise(session, "Çarşambaya Kuru Fasulye koy.")
    after = {item.date: item.recipe.name for item in revised.meal_plan.items}

    target = date(2026, 9, 2)
    assert after[target] == "Kuru Fasulye"
    for day, recipe_name in before.items():
        if day != target:
            assert after[day] == recipe_name


def test_excluded_inactive_recipes_are_not_candidates(db):
    RecipeService(db).disable_recipe("Makarna")
    selected = CandidateSelector(db).select("dinner", [], date(2026, 8, 31), recent_weeks=3)
    assert "Makarna" not in {recipe.name for recipe in selected}

