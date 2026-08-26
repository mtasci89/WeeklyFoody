from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import Base
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        admin_telegram_user_id=111,
        telegram_recipient_chat_ids=[222, 333],
        default_servings=4,
        meal_slots=["dinner"],
        llm_provider="rule",
        openai_api_key="",
    )


@pytest.fixture()
def db(settings: Settings):
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    try:
        seed_recipes(session)
        yield session
    finally:
        session.close()
        engine.dispose()


def seed_recipes(db):
    service = RecipeService(db)
    recipes = [
        RecipeInput(
            name="Fırında Tavuk",
            meal_type="dinner",
            servings=4,
            protein_type="chicken",
            ingredients=[IngredientInput(name="tavuk", quantity=1000, unit="g"), IngredientInput(name="patates", quantity=4, unit="adet")],
        ),
        RecipeInput(
            name="Kuru Fasulye",
            meal_type="dinner",
            servings=4,
            protein_type="legumes",
            ingredients=[IngredientInput(name="kuru fasulye", quantity=500, unit="g"), IngredientInput(name="soğan", quantity=2, unit="adet")],
        ),
        RecipeInput(
            name="Izgara Balık",
            meal_type="dinner",
            servings=4,
            protein_type="fish",
            ingredients=[IngredientInput(name="balık", quantity=1000, unit="g"), IngredientInput(name="limon", quantity=2, unit="adet")],
        ),
        RecipeInput(
            name="Makarna",
            meal_type="dinner",
            servings=4,
            protein_type="wheat",
            ingredients=[IngredientInput(name="makarna", quantity=500, unit="g"), IngredientInput(name="domates", quantity=3, unit="adet")],
        ),
        RecipeInput(
            name="Izgara Köfte",
            meal_type="dinner",
            servings=4,
            protein_type="beef",
            ingredients=[IngredientInput(name="kıyma", quantity=600, unit="g"), IngredientInput(name="soğan", quantity=1, unit="adet")],
        ),
        RecipeInput(
            name="Nohut",
            meal_type="dinner",
            servings=4,
            protein_type="legumes",
            ingredients=[IngredientInput(name="nohut", quantity=500, unit="g"), IngredientInput(name="soğan", quantity=1, unit="adet")],
        ),
        RecipeInput(
            name="Sebze Yemeği",
            meal_type="dinner",
            servings=4,
            protein_type="vegetable",
            ingredients=[IngredientInput(name="kabak", quantity=2, unit="adet"), IngredientInput(name="havuç", quantity=2, unit="adet")],
        ),
    ]
    for recipe in recipes:
        service.upsert_recipe(recipe)

