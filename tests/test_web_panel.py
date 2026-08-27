from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import Base
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService
from app.web_panel import create_web_app


def make_panel(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'panel.db'}",
        web_panel_token="secret",
        telegram_bot_token="",
        llm_provider="rule",
        gemini_api_key="",
        openai_api_key="",
    )
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        RecipeService(db).upsert_recipe(
            RecipeInput(
                name="Panel Köfte",
                category="main",
                ingredients=[IngredientInput(name="kıyma", quantity=500, unit="g")],
            )
        )
        RecipeService(db).upsert_recipe(
            RecipeInput(
                name="Panel Haydari",
                category="meze",
                ingredients=[IngredientInput(name="yoğurt", quantity=300, unit="g")],
            )
        )
    return TestClient(create_web_app(settings, Session))


def test_web_panel_requires_token(tmp_path):
    client = make_panel(tmp_path)

    response = client.get("/")

    assert response.status_code == 401


def test_web_panel_lists_recipes(tmp_path):
    client = make_panel(tmp_path)

    response = client.get("/recipes?token=secret")

    assert response.status_code == 200
    assert "Panel Köfte" in response.text
    assert "Panel Haydari" in response.text


def test_web_panel_api_returns_recipes(tmp_path):
    client = make_panel(tmp_path)

    response = client.get("/api/recipes?token=secret")

    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {"Panel Köfte", "Panel Haydari"}
