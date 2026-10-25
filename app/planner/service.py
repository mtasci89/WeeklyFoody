from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, base_meal_slot, course_role
from app.db.models import MealPlan, MealPlanItem, Recipe, SessionState, WeeklyPlanningSession
from app.llm.base import WeeklyPlanOutput, PlannedMeal
from app.llm.rule_based import RuleBasedLLMProvider
from app.llm import build_llm_provider
from app.memory.preferences import PreferenceService
from app.planner.candidate_selector import CandidateSelector
from app.planner.dates import next_week_start, week_dates, week_end
from app.planner.scorer import CandidateScorer
from app.planner.validator import PlanValidator, PlanValidationError

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
        if session is None:
            session = WeeklyPlanningSession(
                week_start=week_start,
                week_end=week_end(week_start),
                state=SessionState.DRAFT_GENERATED,
                admin_chat_id=self.settings.admin_telegram_user_id,
            )
            self.db.add(session)
            self.db.flush()
        expected_version = session.draft_version
        output = await self._generate_structured_plan(week_start)
        self.db.refresh(session)
        if session.draft_version != expected_version:
            raise ValueError("Menü bu sırada değişti. Son sürümü inceleyip tekrar dene.")
        if regenerate and session.meal_plan:
            remember_published_plan(session)
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
        candidates_by_slot: dict[str, list[Recipe]] = {}
        used_proteins: Counter[str] = Counter()
        for target_date in dates:
            for slot in self.settings.planning_slots:
                role = course_role(slot)
                candidates = selector.select(base_meal_slot(slot), hard, week_start, course_role=role)
                if not candidates:
                    raise ValueError(f"{role} için uygun onaylı tarif yok. Önce bu kategoride tarif ekle.")
                scored = scorer.score(candidates, target_date, used_proteins)
                if scored:
                    selected = scored[:20]
                    candidates_by_slot.setdefault(slot, [])
                    candidates_by_slot[slot].extend(recipe for recipe in selected if recipe not in candidates_by_slot[slot])
                    candidate_pool.extend(recipe for recipe in selected if recipe not in candidate_pool)
                    used_proteins[selected[0].protein_type or selected[0].category] += 1
        context = {
            "household": {"default_servings": self.settings.default_servings},
            "meal_slots": self.settings.planning_slots,
            "base_meal_slots": self.settings.meal_slots,
            "meal_course_roles": self.settings.meal_course_roles,
            "slot_requirements": {slot: {"role": course_role(slot), "allowed_categories": allowed_categories_for_role(course_role(slot))} for slot in self.settings.planning_slots},
            "dates": [d.isoformat() for d in dates],
            "hard_preferences": hard,
            "soft_preferences": PreferenceService(self.db).soft_rules(),
            "candidate_recipes": [self._recipe_context(recipe) for recipe in candidate_pool[:60]],
            "candidate_recipes_by_slot": {
                slot: [self._recipe_context(recipe) for recipe in recipes[:25]] for slot, recipes in candidates_by_slot.items()
            },
            "recent_meals": self._recent_meals(limit=28),
            "serving_overrides": {},
        }
        output = await self.llm.generate_plan(context)
        try:
            PlanValidator(self.db).validate(output, dates, self.settings.planning_slots, hard)
        except PlanValidationError:
            logger.warning("invalid_llm_plan_using_local_fallback")
            output = await RuleBasedLLMProvider().generate_plan(context)
            PlanValidator(self.db).validate(output, dates, self.settings.planning_slots, hard)
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
        PlanValidator(self.db).validate(
            plan_output(session), week_dates(session.week_start), self.settings.planning_slots,
            PreferenceService(self.db).hard_rules(),
        )
        session.state = SessionState.APPROVED
        session.meal_plan.status = "final"
        self.db.commit()
        logger.info("plan_approved week_start=%s session_id=%s", session.week_start, session.id)

    def current_session(self, week_start: date | None = None) -> WeeklyPlanningSession | None:
        if week_start is not None:
            return self.db.scalar(select(WeeklyPlanningSession).where(WeeklyPlanningSession.week_start == week_start))
        upcoming = self.current_session(next_week_start(timezone=self.settings.timezone))
        if upcoming:
            return upcoming
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        return self.current_session(today - timedelta(days=today.weekday()))

    def session_for_message(self, message: str) -> WeeklyPlanningSession | None:
        text = message.casefold()
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        if "gelecek hafta" in text or "önümüzdeki hafta" in text:
            return self.current_session(next_week_start(today))
        if "bu hafta" in text:
            return self.current_session(today - timedelta(days=today.weekday())) or self.current_session()
        return self.current_session()

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


def allowed_categories_for_role(role: str) -> list[str]:
    normalized = role.casefold()
    if normalized == "main":
        return ["main"]
    if normalized in {"meze", "salad"}:
        return ["meze", "salad"]
    if normalized == "side":
        return ["side", "soup", "grain", "pasta", "pilaf"]
    return [normalized]


def plan_output(session: WeeklyPlanningSession) -> WeeklyPlanOutput:
    return WeeklyPlanOutput(meals=[
        PlannedMeal(date=item.date.isoformat(), meal_slot=item.meal_slot, recipe_id=item.recipe_id, servings=item.servings)
        for item in session.meal_plan.items
    ])


def remember_published_plan(session: WeeklyPlanningSession) -> None:
    context = dict(session.context or {})
    if session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
        context["previous_final"] = plan_output(session).model_dump()
        context["previous_final_version"] = session.draft_version
    context.pop("clarification", None)
    session.context = context
    session.published_at = None

