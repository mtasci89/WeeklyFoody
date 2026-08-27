from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MealPlanItem, Recipe, RecipeStatus, SessionState, WeeklyPlanningSession


class CandidateSelector:
    def __init__(self, db: Session):
        self.db = db

    def select(self, meal_slot: str, hard_rules: list[str], week_start: date, recent_weeks: int = 3, course_role: str | None = None) -> list[Recipe]:
        recipes = list(
            self.db.scalars(
                select(Recipe).where(Recipe.status == RecipeStatus.APPROVED, Recipe.meal_type == meal_slot).order_by(Recipe.name)
            )
        )
        excluded = self._excluded_terms(hard_rules)
        recent_ids = self._recent_recipe_ids(week_start, recent_weeks)
        filtered = []
        for recipe in recipes:
            text = " ".join(
                [
                    recipe.name,
                    recipe.protein_type or "",
                    " ".join(recipe.tags or []),
                    " ".join(ri.ingredient.name for ri in recipe.ingredients),
                ]
            ).casefold()
            if any(term in text for term in excluded):
                continue
            if course_role and not self._matches_course_role(recipe, course_role):
                continue
            filtered.append(recipe)
        less_recent = [recipe for recipe in filtered if recipe.id not in recent_ids]
        return less_recent or filtered

    def _matches_course_role(self, recipe: Recipe, course_role: str) -> bool:
        category = (recipe.category or "main").casefold()
        name = recipe.name.casefold()
        tags = {tag.casefold() for tag in recipe.tags or []}
        role = course_role.casefold()
        if role == "main":
            return category == "main"
        if role in {"meze", "salad"}:
            return category in {"meze", "salad"} or "meze" in tags or "salata" in name or "salad" in name
        if role == "side":
            return category in {"side", "soup", "grain", "pasta", "pilaf"} or any(
                token in name for token in ("çorba", "pilav", "makarna", "kinoa", "quinoa", "bulgur")
            )
        return category == role

    def _recent_recipe_ids(self, week_start: date, recent_weeks: int) -> set[str]:
        cutoff = week_start - timedelta(weeks=recent_weeks)
        rows = self.db.scalars(
            select(MealPlanItem)
            .join(MealPlanItem.plan)
            .join(WeeklyPlanningSession)
            .where(WeeklyPlanningSession.week_start >= cutoff, WeeklyPlanningSession.state.in_([SessionState.APPROVED, SessionState.PUBLISHED]))
        )
        return {row.recipe_id for row in rows}

    def _excluded_terms(self, hard_rules: list[str]) -> set[str]:
        terms: set[str] = set()
        markers = ("önerme", "olmasın", "yasak", "yeme", "avoid", "exclude", "do not suggest")
        for rule in hard_rules:
            lower = rule.casefold()
            if any(marker in lower for marker in markers):
                words = [w.strip(".,;:!?") for w in lower.split()]
                stop = {"bundan", "sonra", "artık", "asla", "bir", "daha", "do", "not", "suggest", "avoid", "exclude", "önerme", "olmasın"}
                terms.update(w for w in words if len(w) > 2 and w not in stop)
        return terms
