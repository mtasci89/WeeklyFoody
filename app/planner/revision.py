from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import MealPlanItem, PreferenceType, SessionState, WeeklyPlanningSession
from app.llm import build_llm_provider
from app.memory.feedback import FeedbackService
from app.memory.preferences import PreferenceService
from app.planner.dates import DAY_TO_INDEX
from app.recipes.service import RecipeService

logger = logging.getLogger(__name__)


class RevisionService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.llm = build_llm_provider(settings)

    async def revise(self, session: WeeklyPlanningSession, message: str) -> WeeklyPlanningSession:
        if not session.meal_plan:
            raise ValueError("No active meal plan")
        if session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
            raise ValueError("Approved plans cannot be revised")
        session.state = SessionState.REVISION_IN_PROGRESS
        self.db.commit()
        recipes = RecipeService(self.db).list_recipes()
        context = {
            "recipes": [{"id": recipe.id, "name": recipe.name} for recipe in recipes],
            "current_plan": [
                {"date": item.date.isoformat(), "day_index": item.date.weekday(), "meal_slot": item.meal_slot, "recipe": item.recipe.name}
                for item in sorted(session.meal_plan.items, key=lambda i: (i.date, i.meal_slot))
            ],
        }
        revision = await self.llm.parse_revision(message, context)
        if revision.needs_clarification:
            session.state = SessionState.AWAITING_ADMIN_FEEDBACK
            session.context = {**(session.context or {}), "clarification": revision.clarification_question}
            self.db.commit()
            return session
        recipe_service = RecipeService(self.db)
        for op in revision.operations:
            target_items = self._target_items(session, op.day_name, op.date, op.meal_slot)
            if op.servings is not None:
                for item in target_items:
                    item.servings = op.servings
            if op.recipe_name:
                replacement = recipe_service.find_recipe(op.recipe_name)
                if replacement:
                    for item in target_items:
                        original = item.recipe_id
                        if original != replacement.id:
                            item.original_recipe_id = item.original_recipe_id or original
                            item.recipe_id = replacement.id
                            item.recipe = replacement
                            item.admin_changed = True
                            item.change_reason = message
                            FeedbackService(self.db).record(
                                message,
                                session_id=session.id,
                                original_recipe_id=original,
                                replacement_recipe_id=replacement.id,
                                context={"date": item.date.isoformat(), "meal_slot": item.meal_slot},
                            )
            elif op.exclude_recipe_name or op.instruction:
                # Minimal deterministic substitution: change only targeted items, choosing the first different approved recipe.
                for item in target_items:
                    replacement = next((r for r in recipes if r.id != item.recipe_id and r.meal_type == item.meal_slot), None)
                    if replacement:
                        original = item.recipe_id
                        item.original_recipe_id = item.original_recipe_id or original
                        item.recipe_id = replacement.id
                        item.recipe = replacement
                        item.admin_changed = True
                        item.change_reason = message
                        FeedbackService(self.db).record(message, session_id=session.id, original_recipe_id=original, replacement_recipe_id=replacement.id)
        if revision.permanent_preference:
            PreferenceService(self.db).add(revision.permanent_preference.rule, PreferenceType(revision.permanent_preference.type), source="telegram")
        session.state = SessionState.AWAITING_APPROVAL
        session.draft_version += 1
        self.db.commit()
        logger.info("draft_revised week_start=%s session_id=%s", session.week_start, session.id)
        return session

    def _target_items(self, session: WeeklyPlanningSession, day_name: str | None, iso_date: str | None, meal_slot: str | None) -> list[MealPlanItem]:
        if not session.meal_plan:
            return []
        target_date = None
        if iso_date:
            from datetime import date

            target_date = date.fromisoformat(iso_date)
        elif day_name:
            target_date = session.week_start + timedelta(days=DAY_TO_INDEX.get(day_name, 0))
        items = list(session.meal_plan.items)
        if target_date:
            items = [item for item in items if item.date == target_date]
        if meal_slot:
            items = [item for item in items if item.meal_slot == meal_slot]
        return items
