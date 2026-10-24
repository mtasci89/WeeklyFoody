from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.nutrition import ESTIMATE_SOURCE, NutritionEstimator
from app.agent.rules import HouseRules
from app.agent.tools import MealAgentToolset
from app.db.models import Base
from app.memory.rules import MealRules
from app.planner.dates import next_week_start, week_dates
from app.recipes.nutrition import NutritionInput, save_nutrition
from app.recipes.service import RecipeService, categorize_ingredient
from app.shopping.aggregator import ShoppingAggregator, ShoppingIngredient
from app.shopping.units import format_shopping_quantity


@pytest.fixture()
def session_factory(db):
    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    return _Factory()


class FakeAsk:
    """Gemini yerine: istenen tariflere sabit degerler dondurur."""

    def __init__(self, values: dict[str, tuple[float, float]] | None = None, raw: str | None = None):
        self.values = values or {}
        self.raw = raw
        self.prompts: list[str] = []

    async def __call__(self, prompt: str, schema: dict) -> str:
        self.prompts.append(prompt)
        if self.raw is not None:
            return self.raw
        rows = [
            {"ad": name, "kcal": kcal, "protein_g": protein}
            for name, (kcal, protein) in self.values.items()
            if f"### {name} (" in prompt
        ]
        return json.dumps({"tarifler": rows})


# --- kural tanima --------------------------------------------------------


@pytest.mark.parametrize(
    "rule",
    [
        "Kalorilerini de yaz yanına",
        "Her yemeğin yanına kişi başı kalorisini yaz",
        "bu menünün 1 kişi için kalorisini de her günün yanına yaz",
        "Günlük kaloriyi de göster",
    ],
)
def test_calorie_display_rules_are_recognised(rule):
    assert MealRules.parse([rule]).show_calories


@pytest.mark.parametrize(
    "rule",
    ["Her akşam bir kişinin toplam kalorisi yazılmasın", "Kalorileri gösterme"],
)
def test_negated_calorie_rules_do_not_turn_display_on(rule):
    assert not MealRules.parse([rule]).show_calories


def test_users_own_examples_become_enforced_rules():
    rules = MealRules.parse(["Bir kişi için bir öğün 1000 kaloriyi geçmesin", "Her akşam 3 farklı yemek olsun"])

    assert rules.max_kcal == 1000
    assert rules.dishes_per_meal == 3
    assert rules.advisory == []


# --- tahmin -------------------------------------------------------------


@pytest.mark.asyncio
async def test_estimator_fills_only_missing_values_and_marks_them_estimated(db):
    service = RecipeService(db)
    kofte, tavuk, corba = (service.find_recipe(n) for n in ("Izgara Köfte", "Fırında Tavuk", "Mercimek Çorbası"))
    save_nutrition(db, kofte, NutritionInput(calories_kcal=610, protein_g=40, source="etiket", estimated=False))
    db.commit()
    ask = FakeAsk({"Izgara Köfte": (1, 1), "Fırında Tavuk": (520, 42), "Mercimek Çorbası": (9000, 10)})

    saved = await NutritionEstimator(ask).fill_missing(db, [kofte, tavuk, corba, tavuk])

    assert saved == ["Fırında Tavuk"]
    assert "### Izgara Köfte (" not in ask.prompts[0]  # dolu olan sorulmaz
    assert (tavuk.nutrition.calories_kcal, tavuk.nutrition.protein_g) == (520, 42)
    assert tavuk.nutrition.estimated and tavuk.nutrition.source == ESTIMATE_SOURCE
    assert kofte.nutrition.calories_kcal == 610  # elle girilen korunur
    assert corba.nutrition is None  # makul olmayan deger kaydedilmez


@pytest.mark.asyncio
async def test_estimator_survives_a_broken_answer(db):
    recipe = RecipeService(db).find_recipe("Fırında Tavuk")

    assert await NutritionEstimator(FakeAsk(raw="bu json değil")).fill_missing(db, [recipe]) == []
    assert recipe.nutrition is None


# --- ajan yolu ----------------------------------------------------------


def _week_rows(*pairs):
    days = week_dates(next_week_start(timezone="Europe/Istanbul"))
    return [f"{days[i].isoformat()}|dinner_{slot}|{name}" for i, slot, name in pairs]


@pytest.mark.asyncio
async def test_plan_kaydet_estimates_calories_when_a_rule_asks_for_them(db, settings, session_factory):
    HouseRules(session_factory).add("Kalorilerini de yaz yanına")
    ask = FakeAsk({"Fırında Tavuk": (520, 42), "Kuru Fasulye": (380, 20)})
    toolset = MealAgentToolset(settings, session_factory, estimator=NutritionEstimator(ask))
    plan_kaydet = next(t for t in toolset.build() if t.name == "plan_kaydet")

    out = await plan_kaydet.call({"ogunler": _week_rows((0, "main", "Fırında Tavuk"), (1, "main", "Kuru Fasulye"))})

    assert "kaydedildi" in out
    assert "520 kcal, 42 g protein / kişi (tahmini)" in out
    assert toolset.touched_session_id is not None


@pytest.mark.asyncio
async def test_no_estimation_without_a_calorie_rule(db, settings, session_factory):
    ask = FakeAsk({"Fırında Tavuk": (520, 42)})
    toolset = MealAgentToolset(settings, session_factory, estimator=NutritionEstimator(ask))
    plan_kaydet = next(t for t in toolset.build() if t.name == "plan_kaydet")

    await plan_kaydet.call({"ogunler": _week_rows((0, "main", "Fırında Tavuk"))})

    assert ask.prompts == []


@pytest.mark.asyncio
async def test_calorie_cap_is_checked_against_estimates(db, settings, session_factory):
    HouseRules(session_factory).add("Bir kişi için bir öğün 1000 kaloriyi geçmesin")
    ask = FakeAsk({"Fırında Tavuk": (700, 42), "Çoban Salata": (450, 3)})
    toolset = MealAgentToolset(settings, session_factory, estimator=NutritionEstimator(ask))
    plan_kaydet = next(t for t in toolset.build() if t.name == "plan_kaydet")

    out = await plan_kaydet.call(
        {"ogunler": _week_rows((0, "main", "Fırında Tavuk"), (0, "salad", "Çoban Salata"))}
    )

    assert "Plan kaydedilmedi" in out
    assert "1000 kcal sınırını aşıyor" in out


# --- Telegram: ozeti sistem ekler --------------------------------------------


@pytest.mark.asyncio
async def test_agent_reply_gets_a_system_calorie_summary(settings, monkeypatch):
    import app.bot.handlers as module
    from app.agent.runner import AgentReply
    from app.planner.service import MealPlannerService

    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(module, "SessionLocal", Session)
    from tests.conftest import seed_recipes

    with Session() as db:
        seed_recipes(db)
        session = await MealPlannerService(db, settings).create_or_get_weekly_session()
        for recipe in {i.recipe for i in session.meal_plan.items}:
            save_nutrition(db, recipe, NutritionInput(calories_kcal=300, protein_g=20, source="t"))
        db.commit()
        session_id = session.id
    HouseRules(Session).add("Kalorilerini de yaz yanına")

    class Agent:
        async def reply(self, chat_id, message, images=None):
            return AgentReply(text="Menü hazır.", plan_session_id=session_id)

    class Bot:
        async def send_message(self, *a, **k):
            pass

        async def send_chat_action(self, *a, **k):
            pass

    class Message:
        def __init__(self):
            self.replies: list[str] = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    class Update:
        effective_message = Message()
        effective_chat = type("C", (), {"id": 1})()
        effective_user = type("U", (), {"id": 1})()

    handlers = module.TelegramHandlers(settings, Bot())
    handlers.agent = Agent()
    update = Update()

    await handlers._agent_turn(update, "menü")

    text = "\n".join(update.effective_message.replies)
    assert text.startswith("Menü hazır.")
    assert "🔥 Kişi başı kalori" in text
    per_day = f"{300 * len(settings.planning_slots):,}".replace(",", ".")
    assert f"Pazartesi: ~{per_day} kcal (" in text
    engine.dispose()


# --- alisveris listesi ------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "unit", "expected"),
    [
        (333.33, "g", "350 g"),
        (40, "g", "40 g"),
        (1499, "g", "1,5 kg"),
        (0.67, "adet", "1 adet"),
        (1.33, "yemek kaşığı", "1,5 yemek kaşığı"),
        (0.25, "tatlı kaşığı", "0,5 tatlı kaşığı"),
    ],
)
def test_shopping_amounts_are_rounded_up_to_buyable_quantities(quantity, unit, expected):
    assert format_shopping_quantity(quantity, unit) == expected


def test_unmeasured_duplicate_of_a_measured_item_is_dropped():
    items = ShoppingAggregator().aggregate(
        [
            ShoppingIngredient("sarımsak", 2, "adet", "Sebze & Meyve"),
            ShoppingIngredient("sarımsak", None, None, "Sebze & Meyve"),
            ShoppingIngredient("tuz", None, None, "Kuru Gıda / Baharat"),
            ShoppingIngredient("tuz", None, None, "Kuru Gıda / Baharat"),
        ]
    )

    assert [i.format() for i in items] == ["tuz", "2 adet sarımsak"]


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("ketçap", "Kuru Gıda / Baharat"),
        ("dana eti", "Et / Tavuk / Balık"),
        ("tavuk but", "Et / Tavuk / Balık"),
        ("pirinç sirkesi", "Kuru Gıda / Baharat"),
        ("sarımsak", "Sebze & Meyve"),
        ("un", "Kuru Gıda / Baharat"),
        ("süzme yoğurt", "Süt Ürünleri"),
    ],
)
def test_ingredient_categories(name, category):
    assert categorize_ingredient(name) == category


@pytest.mark.asyncio
async def test_recipe_detail_scales_to_the_household(db, settings, session_factory):
    toolset = MealAgentToolset(settings, session_factory)
    detail = next(t for t in toolset.build() if t.name == "tarif_detay")

    out = await detail.call({"tarif_adi": "Fırında Tavuk", "kisi": 2})

    # Tarif 4 kisilik ve 1000 g tavuk: 2 kisi icin 500 g
    assert "2 kişi için malzemeler" in out
    assert "500 g tavuk" in out
