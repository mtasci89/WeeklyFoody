from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.bot.security import TelegramSecurity
from app.config import Settings
from app.db.models import Base, SessionState, WeeklyPlanningSession
from app.planner.service import MealPlannerService
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService
from app.workflow import WeeklyWorkflowService


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.messages.append((chat_id, text, kwargs))


@pytest.mark.asyncio
async def test_cannot_publish_before_approval(db, settings):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(date(2026, 8, 31))
    with pytest.raises(ValueError):
        await WeeklyWorkflowService(db, settings, FakeNotifier()).publish_final(session)


@pytest.mark.asyncio
async def test_publishing_sends_final_only_once(db, settings):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(date(2026, 8, 31))
    planner.approve(session)
    notifier = FakeNotifier()
    assert await WeeklyWorkflowService(db, settings, notifier).publish_final(session) is True
    assert await WeeklyWorkflowService(db, settings, notifier).publish_final(session) is False
    assert len(notifier.messages) == 3
    assert session.state == SessionState.PUBLISHED


def test_telegram_security_blocks_recipient_approval(settings):
    security = TelegramSecurity(settings)
    assert security.is_admin(111)
    assert not security.require_admin(222)


def test_recipes_survive_restart(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'persist.db'}"
    engine = create_engine(db_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        RecipeService(db).upsert_recipe(RecipeInput(name="Restart Yemeği", ingredients=[IngredientInput(name="pirinç", quantity=100, unit="g")]))
    with Session() as db:
        assert RecipeService(db).find_recipe("Restart Yemeği") is not None


@pytest.mark.asyncio
async def test_weekly_state_survives_restart(tmp_path, settings):
    db_url = f"sqlite:///{tmp_path / 'state.db'}"
    test_settings = Settings(**{**settings.model_dump(), "database_url": db_url})
    engine = create_engine(db_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        from conftest import seed_recipes

        seed_recipes(db)
        session = await MealPlannerService(db, test_settings).create_or_get_weekly_session(date(2026, 8, 31))
        session_id = session.id
    with Session() as db:
        restored = db.query(WeeklyPlanningSession).filter_by(week_start=date(2026, 8, 31)).one()
        assert restored.id == session_id
        assert restored.state == SessionState.AWAITING_ADMIN_FEEDBACK
