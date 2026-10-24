"""Malzemesi kaydedilmemiş tariflerin tamamlanması.

Kullanıcı ekran görüntüsü: Tarifler > Bu hafta'da "Brokoli Çorbası", "Mercimek Çorbası",
"Fırında Püreli Tavuk" boş. Bunlar eski menü Excel'inden yalnızca adlarıyla gelmişti;
alışveriş listesine de hiçbir şey eklemiyorlardı.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.recipe_fill import NOTE, fill_recipes
from app.api import create_api_app
from app.db.models import Base, RecipeStatus
from app.planner.dates import next_week_start
from app.planner.service import MealPlannerService
from app.recipes.importer import RecipeInput
from app.recipes.service import RecipeService
from tests.conftest import seed_recipes

WEEK = next_week_start(timezone="Europe/Istanbul")


class Asker:
    def __init__(self, rows):
        self.rows = rows
        self.prompts: list[str] = []

    async def __call__(self, prompt, schema):
        self.prompts.append(prompt)
        return json.dumps({"tarifler": self.rows})


def name_only(db, name, category="soup"):
    return RecipeService(db).upsert_recipe(
        RecipeInput(name=name, category=category, meal_type="dinner",
                    notes="Imported from historical menu list; ingredients can be taught later.")
    )


BROKOLI = {
    "ad": "Brokoli Çorbası",
    "porsiyon": 4,
    "malzemeler": ["1 adet brokoli", "1 adet soğan", "2 yemek kaşığı tereyağı", "1 su bardağı süt"],
    "hazirlanis": "Soğanı kavur. Brokoliyi ekle, su koy, pişir. Blenderdan geçir, sütü ekle.",
    "pisirme_dakika": 25,
}


@pytest.mark.asyncio
async def test_name_only_recipes_get_ingredients_and_steps(db):
    soup = name_only(db, "Brokoli Çorbası")
    other = RecipeService(db).find_recipe("Fırında Tavuk")
    before = [i.ingredient.name for i in other.ingredients]
    asker = Asker([BROKOLI, {"ad": "Uydurma", "malzemeler": ["1 x", "2 y"], "hazirlanis": "x"}])

    done = await fill_recipes(db, asker, [soup, other, soup])

    assert done == ["Brokoli Çorbası"]
    soup = RecipeService(db).find_recipe("Brokoli Çorbası")
    assert [i.ingredient.name for i in soup.ingredients][:2] == ["brokoli", "soğan"]
    assert soup.instructions.startswith("Soğanı kavur") and soup.cook_minutes == 25
    assert soup.notes == NOTE and soup.status == RecipeStatus.APPROVED and soup.category == "soup"
    assert [i.ingredient.name for i in other.ingredients] == before  # dolu tarife dokunulmaz
    assert "Brokoli Çorbası" in asker.prompts[0] and "Fırında Tavuk" not in asker.prompts[0]
    # İkinci kez sorulmaz
    assert await fill_recipes(db, asker, [soup]) == [] and len(asker.prompts) == 1


@pytest.mark.asyncio
async def test_a_broken_answer_or_no_ai_changes_nothing(db):
    soup = name_only(db, "Brokoli Çorbası")

    async def broken(prompt, schema):
        return "bu json değil"

    assert await fill_recipes(db, broken, [soup]) == []
    assert await fill_recipes(db, None, [soup]) == []
    assert not RecipeService(db).find_recipe("Brokoli Çorbası").ingredients


TOKEN = "f" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.mark.asyncio
async def test_menu_recipes_and_shopping_list_are_completed_on_request(settings):
    gem = settings.model_copy(update={"app_api_token": TOKEN, "agent_provider": "gemini", "gemini_api_key": "x"})
    engine = create_engine(gem.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        seed_recipes(db)
        name_only(db, "Brokoli Çorbası", category="soup")
        session = await MealPlannerService(db, gem).create_or_get_weekly_session(WEEK)
        soup = RecipeService(db).find_recipe("Brokoli Çorbası")
        session.meal_plan.items[1].recipe_id = soup.id  # bir yan yemeğin yerine
        db.commit()
    asker = Asker([BROKOLI])

    class Agent:
        class store:
            @staticmethod
            def history(chat_id):
                return []

        def estimator(self):
            class E:
                ask_json = asker
            return E()

    client = TestClient(create_api_app(gem, Session, agent=Agent()))

    recipes = client.get("/api/v1/menu/tarifler", headers=AUTH, params={"hafta": "gelecek_hafta"}).json()["tarifler"]
    shopping = client.get("/api/v1/alisveris", headers=AUTH, params={"hafta": "gelecek_hafta"}).json()

    brokoli = next(r for r in recipes if r["ad"] == "Brokoli Çorbası")
    assert [m["ad"] for m in brokoli["malzemeler"]][:1] == ["brokoli"] and brokoli["hazirlanis"]
    items = [k["ad"] for g in shopping["gruplar"] for k in g["kalemler"]]
    assert "brokoli" in items
    engine.dispose()
