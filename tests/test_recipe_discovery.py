from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models import RecipeStatus
from app.llm.base import Intent
from app.llm.rule_based import RuleBasedLLMProvider
from app.recipes.importer import IngredientInput, PlainTextRecipeImporter, RecipeInput
from app.recipes.service import RecipeService
from app.recipes.weekly_discovery import WeeklyRecipeDiscoveryService
from app.scheduler.weekly import build_scheduler


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


def test_modern_trend_seed_recipes_import(db):
    count = RecipeService(db).import_recipes(Path("data/recipes/modern_healthy_trends.yaml"))

    assert count == 26
    assert RecipeService(db).find_recipe("Datça Güzeli").category == "meze"
    assert RecipeService(db).find_recipe("Chicken Caesar Smash Taco").category == "main"
    assert RecipeService(db).find_recipe("Kırmızı Mercimek Lavaşı").category == "side"


@pytest.mark.asyncio
async def test_weekly_discovery_noops_without_provider_key(db, settings):
    no_provider_settings = settings.model_copy(update={"gemini_api_key": "", "openai_api_key": ""})
    candidates = await WeeklyRecipeDiscoveryService(db, no_provider_settings).discover_candidates()

    assert candidates == []


def test_scheduler_registers_recipe_discovery_job(settings):
    scheduler = build_scheduler(settings)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "weekly_meal_plan" in job_ids
    assert "weekly_recipe_discovery" in job_ids


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


# --- web'de arayan kesif (ajan) ----------------------------------------


class _FakeAgentReply:
    def __init__(self, text: str):
        self.text = text
        self.ok = True
        self.plan_session_id = None


class _FakeAgent:
    def __init__(self, *args, **kwargs):
        self.prompts: list[str] = []

    @classmethod
    def available(cls, settings):
        return True

    async def reply(self, chat_id, message, images=None, timeout=None):
        self.prompts.append(message)
        return _FakeAgentReply(f"eklendi #{len(self.prompts)}")

    async def aclose(self):
        pass


class _FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

    async def send_chat_action(self, *args, **kwargs):
        pass


def test_discovery_prompt_asks_for_web_search_and_candidates():
    from app.agent.prompts import discovery_prompt

    prompt = discovery_prompt("pratik tavuk yemeği", limit=2)

    assert "pratik tavuk yemeği" in prompt
    assert "en fazla 2" in prompt
    assert "tarif_ekle" in prompt and "ADAY" in prompt
    assert "kaynağıyla" in prompt


@pytest.mark.asyncio
async def test_discover_command_runs_a_web_searching_agent_turn(settings):
    from app.bot.handlers import TelegramHandlers

    class Message:
        text = "/discover pratik tavuk yemeği"

        def __init__(self):
            self.replies: list[str] = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    class Update:
        effective_message = Message()
        effective_user = type("U", (), {"id": settings.admin_telegram_user_id})()
        effective_chat = type("C", (), {"id": settings.admin_telegram_user_id})()

    class Context:
        args = ["pratik", "tavuk", "yemeği"]

    handlers = TelegramHandlers(settings, _FakeBot())
    handlers.agent = _FakeAgent()
    update = Update()

    await handlers.discover(update, Context())

    assert "İnternette arıyorum" in update.effective_message.replies[0]
    assert update.effective_message.replies[-1] == "eklendi #1"
    assert "pratik tavuk yemeği" in handlers.agent.prompts[0]


@pytest.mark.asyncio
async def test_weekly_discovery_searches_each_category_and_reports_to_admin(settings, monkeypatch):
    import app.agent.runner as runner
    import app.scheduler.weekly as weekly

    agents: list[_FakeAgent] = []

    def make(*args, **kwargs):
        agent = _FakeAgent()
        agents.append(agent)
        return agent

    make.available = _FakeAgent.available
    bot = _FakeBot()
    configured = settings.model_copy(update={"recipe_discovery_queries": ["ana yemek", "meze"]})
    monkeypatch.setattr(runner, "MealPlannerAgent", make)
    monkeypatch.setattr(weekly, "get_settings", lambda: configured)
    monkeypatch.setattr(weekly, "_CURRENT_BOT", bot)

    await weekly.weekly_recipe_discovery_job()

    assert len(agents[0].prompts) == 2
    assert "ana yemek" in agents[0].prompts[0] and "meze" in agents[0].prompts[1]
    admin, text = bot.sent[0]
    assert admin == settings.admin_telegram_user_id
    assert "eklendi #1" in text and "eklendi #2" in text
    assert "/candidates" in text
