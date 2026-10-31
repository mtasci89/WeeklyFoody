"""Günün tabağı: ana yemek ile yan yemeğin uyumu.

Kullanıcı: "Günlük yemek ve yan yemeğin birbiriyle uyumuna da dikkat etsin,
alakasız olmasınlar." Yasak değil; not + yumuşak tercih.
"""
from __future__ import annotations

import pytest

from app.agent.fresh import build_batch_prompt
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import variety_notes
from app.llm.rule_based import RuleBasedLLMProvider, constrained_plan
from app.planner.pairing import cuisine_family, pairing_issues, pairing_penalty
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService
from test_no_repeat import DAYS, FakeEstimator, idea, library, plan, toolset_for  # noqa: F401


def test_pairing_issues_spot_unrelated_plates():
    assert any("mutfak" in i for i in pairing_issues("Kore Usulü Tavuk", "Bulgur Pilavı"))
    assert any("nişasta" in i for i in pairing_issues("Fırın Makarna", "Pirinç Pilavı"))
    assert any("nohut" in i for i in pairing_issues("Nohutlu Tavuk", "Nohut Salatası"))
    # Klasik eşleşmeler uyumlu sayılır.
    assert pairing_issues("Kuru Fasulye", "Pirinç Pilavı") == []
    assert pairing_issues("Izgara Köfte", "Piyaz") == []
    assert pairing_issues("Tavuk Fajita", "Guacamole") == []


def test_cuisine_from_saved_field_or_name():
    assert cuisine_family({"name": "Tavuk Sote", "cuisine": "korean"}) == "Asya"
    assert cuisine_family("Tavuk Teriyaki") == "Asya"
    assert cuisine_family("Fırında Tavuk") == ""  # bilinmeyen: hiçbir şey denmez


def _add(db, name, category):
    RecipeService(db).upsert_recipe(
        RecipeInput(name=name, category=category, meal_type="dinner",
                    ingredients=[IngredientInput(name="x", quantity=1, unit="adet")])
    )


def test_variety_notes_mention_plate_mismatch_as_a_note(library):
    _add(library, "Kore Usulü Tavuk", "main")
    _add(library, "Bulgur Pilavı", "side")
    session = plan(library, [(0, "dinner_main", "Kore Usulü Tavuk"), (0, "dinner_side", "Bulgur Pilavı")])

    notes = variety_notes(session)

    assert any(n.startswith("Tabak uyumu") and "Bulgur Pilavı" in n and "mutfak" in n for n in notes)


def test_prompt_tells_the_agent_to_think_about_the_plate():
    assert "Günün tabağı bir bütündür" in SYSTEM_PROMPT


def test_batch_prompt_shows_the_days_plate():
    prompt = build_batch_prompt(
        [("side", "Salı 2026-11-03", "Bulgur Pilavı", "Ana yemek: Kore Usulü Tavuk")], "", [], [], []
    )
    assert "o günün tabağında: Ana yemek: Kore Usulü Tavuk" in prompt
    assert "Günün tabağı bir bütün" in prompt


@pytest.mark.asyncio
async def test_new_side_dish_prefers_one_that_suits_the_main(library, settings):
    _add(library, "Kore Usulü Tavuk", "main")
    _add(library, "Bulgur Pilavı", "side")
    session = plan(library, [(0, "dinner_main", "Kore Usulü Tavuk"), (0, "dinner_side", "Bulgur Pilavı")])
    estimator = FakeEstimator([
        idea("Firik Pilavı Zeytinyağlı", icin=1),  # Türk: Asya ana yemeğe uymaz
        idea("Susamlı Soya Soslu Brokoli", icin=1),
    ])
    _, tools = toolset_for(library, settings, estimator)

    out = await tools["yenisiyle_degistir"].call({"ogunler": [f"{DAYS[0].isoformat()}|dinner_side"]})

    assert "Susamlı Soya Soslu Brokoli" in out
    side = next(i for i in session.meal_plan.items if i.meal_slot == "dinner_side")
    assert side.recipe.name == "Susamlı Soya Soslu Brokoli"
    assert "Kore Usulü Tavuk" in estimator.prompts[0]


def _ctx(**extra):
    main = {"id": "m", "name": "Fırın Makarna", "category": "main"}
    sides = [
        {"id": "s1", "name": "Pirinç Pilavı", "category": "side"},
        {"id": "s2", "name": "Mercimek Çorbası", "category": "soup"},
    ]
    return {
        "meal_slots": ["dinner_main", "dinner_side"], "dates": ["2026-11-02"],
        "candidate_recipes": [main, *sides],
        "candidate_recipes_by_slot": {"dinner_main": [main], "dinner_side": sides},
        **extra,
    }


@pytest.mark.asyncio
async def test_fallback_planner_picks_the_side_that_suits_the_main():
    plan_out = await RuleBasedLLMProvider().generate_plan(_ctx())
    assert [m.recipe_id for m in plan_out.meals] == ["m", "s2"]
    assert pairing_penalty("Fırın Makarna", "Pirinç Pilavı") > 0


def test_constrained_planner_also_prefers_a_suitable_side():
    out = constrained_plan(_ctx(distinct_dishes=True))
    assert [m.recipe_id for m in out.meals] == ["m", "s2"]
