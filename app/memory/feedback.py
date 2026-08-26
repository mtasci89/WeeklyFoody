from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Feedback


class FeedbackService:
    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        admin_text: str,
        session_id: str | None = None,
        original_recipe_id: str | None = None,
        replacement_recipe_id: str | None = None,
        permanent: bool = False,
        context: dict | None = None,
    ) -> Feedback:
        feedback = Feedback(
            session_id=session_id,
            original_recipe_id=original_recipe_id,
            replacement_recipe_id=replacement_recipe_id,
            admin_text=admin_text,
            permanent=permanent,
            context=context or {},
        )
        self.db.add(feedback)
        self.db.commit()
        self.db.refresh(feedback)
        return feedback

    def rejected_counts(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        for row in self.db.scalars(select(Feedback).where(Feedback.original_recipe_id.is_not(None))):
            counts[row.original_recipe_id] += 1
        return counts

    def accepted_counts(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        for row in self.db.scalars(select(Feedback).where(Feedback.replacement_recipe_id.is_not(None))):
            counts[row.replacement_recipe_id] += 1
        return counts

