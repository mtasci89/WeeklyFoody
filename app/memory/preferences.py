from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Preference, PreferenceType


class PreferenceService:
    def __init__(self, db: Session):
        self.db = db

    def add(self, rule: str, type_: PreferenceType = PreferenceType.HARD, source: str | None = None, weight: float = 1.0) -> Preference:
        preference = Preference(rule=rule.strip(), type=type_, source=source, weight=weight)
        self.db.add(preference)
        self.db.commit()
        self.db.refresh(preference)
        return preference

    def delete(self, query: str) -> bool:
        preferences = self.active()
        query_lower = query.casefold()
        for pref in preferences:
            if pref.id == query or query_lower in pref.rule.casefold():
                pref.active = False
                self.db.commit()
                return True
        return False

    def active(self, type_: PreferenceType | None = None) -> list[Preference]:
        stmt = select(Preference).where(Preference.active.is_(True))
        if type_:
            stmt = stmt.where(Preference.type == type_)
        return list(self.db.scalars(stmt.order_by(Preference.created_at.desc())))

    def hard_rules(self) -> list[str]:
        return [p.rule for p in self.active(PreferenceType.HARD)]

    def soft_rules(self) -> list[str]:
        return [p.rule for p in self.active(PreferenceType.SOFT)]

