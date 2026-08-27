from __future__ import annotations

import pytest

from app.db.models import RecipeStatus
from app.llm.base import Intent
from app.llm.rule_based import RuleBasedLLMProvider
from app.recipes.importer import IngredientInput, PlainTextRecipeImporter, RecipeInput
from app.recipes.service import RecipeService


def test_candidate_can_be_approved(db):
    service = RecipeService(db)
    service.upsert_recipe(
        RecipeInput(
            name="Tavuk Fajita",
            status="candidate",
            ingredients=[IngredientInput(name="tavuk", quantity=600, unit="g")],
        )
    )

    assert service.approve_candidate("Tavuk Fajita")
    assert service.find_recipe("Tavuk Fajita").status == RecipeStatus.APPROVED


def test_discovery_does_not_downgrade_existing_approved_recipe(db):
    service = RecipeService(db)
    original = service.find_recipe("Fırında Tavuk")

    result = service.upsert_recipe(RecipeInput(name="Fırında Tavuk", status="candidate"))

    assert result.id == original.id
    assert result.status == RecipeStatus.APPROVED
    assert len(result.ingredients) > 0


def test_plain_text_recipe_importer_keeps_instagram_url_as_source():
    recipe = PlainTextRecipeImporter().parse_text(
        "/addrecipe Tavuk Fajita\nhttps://www.instagram.com/reel/example\n600 gr tavuk\n2 biber"
    )

    assert recipe.name == "Tavuk Fajita"
    assert recipe.source == "https://www.instagram.com/reel/example"
    assert [ingredient.name for ingredient in recipe.ingredients] == ["tavuk", "biber"]


@pytest.mark.asyncio
async def test_rule_router_detects_recipe_discovery():
    routed = await RuleBasedLLMProvider().route_intent("Yeni bir tavuk yemeği bul")

    assert routed.intent == Intent.DISCOVER_RECIPE
    assert routed.discovery_query == "Yeni bir tavuk yemeği bul"


@pytest.mark.asyncio
async def test_rule_router_distinguishes_recipe_add_from_discovery():
    routed = await RuleBasedLLMProvider().route_intent("yeni tarif ekle")

    assert routed.intent == Intent.ADD_RECIPE
    assert routed.recipe_text is None


@pytest.mark.asyncio
async def test_rule_router_detects_plain_recipe_text():
    routed = await RuleBasedLLMProvider().route_intent("Tavuk Fajita\n600 gr tavuk\n2 biber")

    assert routed.intent == Intent.ADD_RECIPE
    assert routed.recipe_text == "Tavuk Fajita\n600 gr tavuk\n2 biber"


@pytest.mark.asyncio
async def test_rule_router_handles_general_questions():
    routed = await RuleBasedLLMProvider().route_intent("Sen ne yapabiliyorsun?")

    assert routed.intent == Intent.GENERAL_QUESTION
    answer = await RuleBasedLLMProvider().answer_general_question("Sen ne yapabiliyorsun?")
    assert "haftalık yemek planı" in answer
