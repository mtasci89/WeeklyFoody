from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.db.models import Recipe, RecipeStatus
from app.llm.base import WeeklyPlanOutput


class PlanValidationError(ValueError):
    pass


class PlanValidator:
    def __init__(self, db: Session):
        self.db = db

    def validate(self, plan: WeeklyPlanOutput, dates: list[date], meal_slots: list[str], hard_rules: list[str]) -> None:
        expected = {(d.isoformat(), slot) for d in dates for slot in meal_slots}
        actual = {(meal.date, meal.meal_slot) for meal in plan.meals}
        if expected != actual:
            missing = expected - actual
            extra = actual - expected
            raise PlanValidationError(f"Invalid meal slots. Missing={missing} Extra={extra}")
        recipe_ids = {meal.recipe_id for meal in plan.meals}
        recipes = {r.id: r for r in self.db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}
        for recipe_id in recipe_ids:
            recipe = recipes.get(recipe_id)
            if not recipe or recipe.status != RecipeStatus.APPROVED:
                raise PlanValidationError(f"Recipe is unavailable: {recipe_id}")
        excluded = self._excluded_terms(hard_rules)
        for meal in plan.meals:
            recipe = recipes[meal.recipe_id]
            text = " ".join([recipe.name, recipe.protein_type or "", " ".join(i.ingredient.name for i in recipe.ingredients)]).casefold()
            if any(term in text for term in excluded):
                raise PlanValidationError(f"Hard preference violation: {recipe.name}")

    def _excluded_terms(self, hard_rules: list[str]) -> set[str]:
        from app.planner.candidate_selector import CandidateSelector

        return CandidateSelector(self.db)._excluded_terms(hard_rules)

