from __future__ import annotations

import logging
from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import MealPlan, MealPlanItem, Recipe, SessionState, WeeklyPlanningSession
from app.llm.base import WeeklyPlanOutput
from app.llm import build_llm_provider
from app.memory.preferences import PreferenceService
from app.planner.candidate_selector import CandidateSelector
from app.planner.dates import next_week_start, week_dates, week_end
from app.planner.scorer import CandidateScorer
from app.planner.validator import PlanValidator

logger = logging.getLogger(__name__)


class MealPlannerService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.llm = build_llm_provider(settings)

    async def create_or_get_weekly_session(self, week_start: date | None = None, regenerate: bool = False) -> WeeklyPlanningSession:
        week_start = week_start or next_week_start(timezone=self.settings.timezone)
        session = self.db.scalar(select(WeeklyPlanningSession).where(WeeklyPlanningSession.week_start == week_start))
        if session and not regenerate:
            return session
        if session and session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
            raise ValueError("Cannot regenerate an approved or published plan")
        if session is None:
            session = WeeklyPlanningSession(
                week_start=week_start,
                week_end=week_end(week_start),
                state=SessionState.DRAFT_GENERATED,
                admin_chat_id=self.settings.admin_telegram_user_id,
            )
            self.db.add(session)
            self.db.flush()
        output = await self._generate_structured_plan(week_start)
        self._persist_plan(session, output, status="draft")
        session.state = SessionState.AWAITING_ADMIN_FEEDBACK
        session.draft_version += 1 if regenerate else 0
        self.db.commit()
        logger.info("draft_generated week_start=%s session_id=%s", week_start, session.id)
        return session

    async def _generate_structured_plan(self, week_start: date) -> WeeklyPlanOutput:
        hard = PreferenceService(self.db).hard_rules()
        selector = CandidateSelector(self.db)
        scorer = CandidateScorer(self.db)
        dates = week_dates(week_start)
        candidate_pool: list[Recipe] = []
        used_proteins: Counter[str] = Counter()
        for target_date in dates:
            for slot in self.settings.meal_slots:
                candidates = selector.select(slot, hard, week_start)
                scored = scorer.score(candidates, target_date, used_proteins)
                if scored:
                    selected = scored[:20]
                    candidate_pool.extend(recipe for recipe in selected if recipe not in candidate_pool)
                    used_proteins[selected[0].protein_type or selected[0].category] += 1
        context = {
            "household": {"default_servings": self.settings.default_servings},
            "meal_slots": self.settings.meal_slots,
            "dates": [d.isoformat() for d in dates],
            "hard_preferences": hard,
            "soft_preferences": PreferenceService(self.db).soft_rules(),
            "candidate_recipes": [self._recipe_context(recipe) for recipe in candidate_pool[:35]],
            "recent_meals": self._recent_meals(limit=28),
            "serving_overrides": {},
        }
        output = await self.llm.generate_plan(context)
        PlanValidator(self.db).validate(output, dates, self.settings.meal_slots, hard)
        return output

    def _persist_plan(self, session: WeeklyPlanningSession, output: WeeklyPlanOutput, status: str) -> MealPlan:
        if session.meal_plan is None:
            plan = MealPlan(session=session, status=status)
            self.db.add(plan)
            self.db.flush()
        else:
            plan = session.meal_plan
            plan.status = status
            plan.items.clear()
            self.db.flush()
        for meal in output.meals:
            plan.items.append(
                MealPlanItem(
                    date=date.fromisoformat(meal.date),
                    meal_slot=meal.meal_slot,
                    recipe_id=meal.recipe_id,
                    servings=meal.servings,
                )
            )
        return plan

    def approve(self, session: WeeklyPlanningSession) -> None:
        if not session.meal_plan:
            raise ValueError("No meal plan exists")
        if session.state == SessionState.PUBLISHED:
            return
        session.state = SessionState.APPROVED
        session.meal_plan.status = "final"
        self.db.commit()
        logger.info("plan_approved week_start=%s session_id=%s", session.week_start, session.id)

    def current_session(self, week_start: date | None = None) -> WeeklyPlanningSession | None:
        week_start = week_start or next_week_start(timezone=self.settings.timezone)
        return self.db.scalar(select(WeeklyPlanningSession).where(WeeklyPlanningSession.week_start == week_start))

    def _recipe_context(self, recipe: Recipe) -> dict:
        return {
            "id": recipe.id,
            "name": recipe.name,
            "category": recipe.category,
            "meal_type": recipe.meal_type,
            "protein_type": recipe.protein_type,
            "vegetarian": recipe.vegetarian,
            "prep_minutes": recipe.prep_minutes,
            "cook_minutes": recipe.cook_minutes,
            "tags": recipe.tags,
        }

    def _recent_meals(self, limit: int) -> list[dict]:
        rows = self.db.scalars(select(MealPlanItem).order_by(MealPlanItem.date.desc()).limit(limit))
        return [{"date": row.date.isoformat(), "recipe_id": row.recipe_id, "recipe": row.recipe.name} for row in rows]

