from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Preference, PreferenceType


class PreferenceService:
    def __init__(self, db: Session):
        self.db = db

    def add(self, rule: str, type_: PreferenceType = PreferenceType.HARD, source: str | None = None, weight: float = 1.0, *, commit: bool = True) -> Preference:
        from app.memory.rules import MealRules
        rule = rule.strip()
        if not rule or len(rule) > 1000:
            raise ValueError("Kural 1–1000 karakter olmalı.")
        hard, soft = self.hard_rules(), self.soft_rules()
        (hard if type_ == PreferenceType.HARD else soft).append(rule)
        MealRules.parse(hard, soft)
        preference = Preference(rule=rule.strip(), type=type_, source=source, weight=weight)
        self.db.add(preference)
        self.db.commit() if commit else self.db.flush()
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


    def document(self) -> str:
        return '\n'.join(('Tercih: ' if p.type == PreferenceType.SOFT else '') + p.rule for p in reversed(self.active()))

    def revision(self) -> str:
        import hashlib
        import json
        records = sorted((p.id, p.rule, p.type.value, p.weight) for p in self.active())
        return hashlib.sha256(json.dumps(records, ensure_ascii=False).encode()).hexdigest()

    def replace_document(self, text: str, expected_revision: str) -> None:
        """Replace only active rules, preserving history and unchanged records."""
        from app.memory.rules import MealRules
        if self.revision() != expected_revision:
            raise PreferenceConflict('Kurallar başka bir yerde değişti. Sayfayı yenileyip değişiklikleri birleştirin.')
        if len(text) > 20000:
            raise ValueError('Kurallar en fazla 20.000 karakter olabilir.')
        entries = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith(('- ', '* ')):
                line = line[2:].strip()
            kind = PreferenceType.HARD
            if line.casefold().startswith('tercih:'):
                kind, line = PreferenceType.SOFT, line.split(':', 1)[1].strip()
            if not line or len(line) > 1000:
                raise ValueError('Her kural 1–1000 karakter olmalı.')
            if (kind, line) not in entries:
                entries.append((kind, line))
        if len(entries) > 100:
            raise ValueError('En fazla 100 kural kaydedilebilir.')
        MealRules.parse([r for k,r in entries if k == PreferenceType.HARD], [r for k,r in entries if k == PreferenceType.SOFT])
        existing = {(p.type, p.rule): p for p in self.active()}
        for p in self.active():
            if (p.type, p.rule) not in entries:
                p.active = False
        for kind, rule in entries:
            if (kind, rule) not in existing:
                self.db.add(Preference(rule=rule, type=kind, source='rules-editor', weight=1.0))
        self.db.commit()


class PreferenceConflict(ValueError):
    pass
