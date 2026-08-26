from __future__ import annotations

from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MealPlanItem, Recipe
from app.memory.feedback import FeedbackService


class CandidateScorer:
    def __init__(self, db: Session):
        self.db = db

    def score(self, candidates: list[Recipe], target_date: date, used_proteins: Counter[str]) -> list[Recipe]:
        rejected = FeedbackService(self.db).rejected_counts()
        accepted = FeedbackService(self.db).accepted_counts()
        last_seen = self._last_seen()
        scored: list[tuple[float, Recipe]] = []
        for recipe in candidates:
            score = 100.0
            if recipe.id in last_seen:
                days_ago = (target_date - last_seen[recipe.id]).days
                score += min(days_ago, 60)
                if days_ago < 21:
                    score -= 80
            else:
                score += 40
            score -= rejected[recipe.id] * 15
            score += accepted[recipe.id] * 10
            effort = (recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)
            if target_date.weekday() < 5 and effort > 75:
                score -= 20
            if target_date.weekday() >= 5 and effort >= 45:
                score += 10
            if recipe.protein_type and used_proteins[recipe.protein_type] > 0:
                score -= used_proteins[recipe.protein_type] * 18
            scored.append((score, recipe))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [recipe for _, recipe in scored]

    def _last_seen(self) -> dict[str, date]:
        rows = self.db.scalars(select(MealPlanItem).order_by(MealPlanItem.date.desc()))
        last: dict[str, date] = {}
        for row in rows:
            last.setdefault(row.recipe_id, row.date)
        return last

