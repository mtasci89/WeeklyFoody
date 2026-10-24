"""Her hafta menüye kütüphane dışından yeni yemek girmesi.

Kullanıcı: "asistanla da olsa tarif listesinden dışarı çıkmıyor, ben her hafta
sıradışı şeyleri de eklesin istiyorum."
"""
from __future__ import annotations

import pytest

from app.api import menu_json
from app.db.models import RecipeStatus
from app.formatting import format_meal_plan
from app.memory.preferences import PreferenceService
from app.memory.rules import MealRules, RuleViolation
from app.planner.dates import next_week_start
from app.planner.novelty import untried_candidates
from app.planner.service import MealPlannerService
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService

WEEK = next_week_start(timezone="Europe/Istanbul")


def candidate(db, name, category="main", ingredient="nohut"):
    return RecipeService(db).upsert_recipe(
        RecipeInput(
            name=name, category=category, meal_type="dinner", status="candidate", source="test",
            ingredients=[IngredientInput(name=ingredient, quantity=1, unit="adet")],
        )
    )


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("Her hafta 2 sıradışı yemek olsun", 2),
        ("haftada üç yeni yemek", 3),
        ("Her hafta iki yeni ve sıradışı yemek denensin", 2),
        ("menüye 1 yeni tarif ekle", 1),
        ("her hafta 2 farklı yemek olsun", 2),
        ("Yeni yemek ekleme", 0),
        ("Sıradışı yemekler istemiyorum", 0),
    ],
)
def test_weekly_new_dish_rules_are_understood(rule, expected):
    rules = MealRules.parse([rule])
    assert rules.new_dishes == expected
    assert not rules.excluded and not rules.advisory


def test_per_meal_count_rule_is_not_mistaken_for_novelty():
    rules = MealRules.parse(["her akşam 2 farklı yemek olsun"])
    assert rules.dishes_per_meal == 2 and rules.new_dishes is None


def test_new_dish_count_has_bounds_and_a_default(settings):
    with pytest.raises(RuleViolation):
        MealRules.parse(["her hafta 9 yeni yemek olsun"])
    assert MealRules().new_dish_target(settings) == settings.weekly_new_dishes == 2
    assert MealRules.parse(["yeni yemek ekleme"]).new_dish_target(settings) == 0


@pytest.mark.asyncio
async def test_automatic_plan_puts_untried_candidates_on_different_days(db, settings):
    candidate(db, "Shakshuka", ingredient="yumurta")
    candidate(db, "Fellah Köftesi", category="meze", ingredient="bulgur")
    candidate(db, "Kimchi Pilav", category="side", ingredient="pirinç")

    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)

    new_items = [i for i in session.meal_plan.items if i.recipe.status == RecipeStatus.CANDIDATE]
    assert len(new_items) == 2
    assert len({i.date for i in new_items}) == 2
    assert all(i.change_reason == "Haftanın yeni yemeği" for i in new_items)
    # Rolüne uygun öğünün yerine geçer
    from app.config import course_role
    from app.planner.candidate_selector import CandidateSelector
    assert all(CandidateSelector(db)._matches_course_role(i.recipe, course_role(i.meal_slot)) for i in new_items)
    # Kullanılan aday artık "denenmemiş" değil; kalan tek aday bekliyor
    assert len(untried_candidates(db)) == 1


@pytest.mark.asyncio
async def test_automatic_plan_respects_house_rules_and_the_off_switch(db, settings):
    candidate(db, "Somonlu Poke", ingredient="somon")
    PreferenceService(db).add("balık kullanma")

    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    assert not [i for i in session.meal_plan.items if i.recipe.status == RecipeStatus.CANDIDATE]

    candidate(db, "Shakshuka", ingredient="yumurta")
    PreferenceService(db).add("yeni yemek ekleme")
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK, regenerate=True)
    assert not [i for i in session.meal_plan.items if i.recipe.status == RecipeStatus.CANDIDATE]


@pytest.mark.asyncio
async def test_new_dishes_are_marked_in_the_app_and_telegram_menus(db, settings):
    candidate(db, "Shakshuka", ingredient="yumurta")
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)

    meals = [m for d in menu_json(db, session, settings)["plan"]["gunler"] for m in d["ogunler"]]
    assert [m["tarif"] for m in meals if m["yeni"]] == ["Shakshuka"]
    assert "Shakshuka ✨ yeni" in format_meal_plan(session)
    # Menüyü onaylamak tarifi kalıcı listeye almaz; aile beğenince onaylanır.
    MealPlannerService(db, settings).approve(session)
    assert RecipeService(db).find_recipe("Shakshuka").status == RecipeStatus.CANDIDATE


@pytest.mark.asyncio
async def test_weekly_job_asks_the_agent_when_no_new_dish_was_found(monkeypatch, db, settings):
    """Cumartesi keşfi aday bulamadıysa pazar taslağına yeni yemeği ajan ekler."""
    import app.agent.runner as runner
    import app.scheduler.weekly as weekly
    from sqlalchemy.orm import sessionmaker

    prompts: list[str] = []

    class FakeAgent:
        def __init__(self, settings, session_factory, **kwargs):
            pass

        @classmethod
        def available(cls, settings):
            return True

        async def reply(self, chat_id, message, **kwargs):
            prompts.append(message)

        async def aclose(self):
            pass

    monkeypatch.setattr(runner, "MealPlannerAgent", FakeAgent)
    monkeypatch.setattr(weekly, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(weekly, "get_settings", lambda: settings)
    monkeypatch.setattr(weekly, "_CURRENT_BOT", None)

    await weekly.weekly_plan_job()

    assert len(prompts) == 1
    assert "2 yeni" in prompts[0] and "internete" in prompts[0] and "onaylama" in prompts[0]


@pytest.mark.asyncio
async def test_weekly_job_skips_the_agent_when_the_target_is_met(monkeypatch, db, settings):
    import app.agent.runner as runner
    import app.scheduler.weekly as weekly
    from sqlalchemy.orm import sessionmaker

    PreferenceService(db).add("yeni yemek ekleme")
    called = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            called.append(True)

        @classmethod
        def available(cls, settings):
            return True

    monkeypatch.setattr(runner, "MealPlannerAgent", FakeAgent)
    monkeypatch.setattr(weekly, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(weekly, "get_settings", lambda: settings)
    monkeypatch.setattr(weekly, "_CURRENT_BOT", None)

    await weekly.weekly_plan_job()

    assert not called


def test_prompt_tells_the_agent_to_search_the_web_when_dishes_are_rejected():
    from app.agent.prompts import SYSTEM_PROMPT, for_provider

    section = SYSTEM_PROMPT.split('## "Bunlar olmamış')[1].split("## Yeni tarif")[0]
    assert "internete MUTLAKA" in section
    assert "ev kurallarına uyarsın" in section
    assert "`ogun_degistir`" in section and "`tarif_ekle`" in section
    assert "`web_ara`" in for_provider(section, "gemini")
    # Eski "kütüphane dışına çıkma" kuralı kalmadı
    assert "Aday tarifleri menüye koymazsın" not in SYSTEM_PROMPT
