"""Haftalık meze listesi: mezeler günlere bölünmez, haftanın ayrı bir listesidir.

Liste öğeleri plan içinde "hafta_meze_N" slotlu, tarihi haftanın ilk günü olan
öğünlerdir; hiçbir günün öğününe sayılmaz (kalori, yemek sayısı), ama alışveriş
listesine bir kez girer.
"""
from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy.orm import Session

from app.config import WEEKLY_BASE, Settings, is_weekly_slot
from app.db.models import MealPlanItem, WeeklyPlanningSession

logger = logging.getLogger(__name__)


def weekly_items(session: WeeklyPlanningSession | None) -> list[MealPlanItem]:
    if session is None or not session.meal_plan:
        return []
    return sorted((i for i in session.meal_plan.items if is_weekly_slot(i.meal_slot)), key=lambda i: i.meal_slot)


def daily_items(session: WeeklyPlanningSession | None) -> list[MealPlanItem]:
    if session is None or not session.meal_plan:
        return []
    return sorted((i for i in session.meal_plan.items if not is_weekly_slot(i.meal_slot)), key=lambda i: (i.date, i.meal_slot))


def next_weekly_slot(existing: set[str], role: str = "meze") -> str:
    index = 1
    while f"{WEEKLY_BASE}_{role}_{index}" in existing:
        index += 1
    return f"{WEEKLY_BASE}_{role}_{index}"


def fill_weekly_mezes(db: Session, settings: Settings, session: WeeklyPlanningSession) -> list[str]:
    """Haftalık meze listesini hedef sayıya tamamlar (kütüphaneden, puan
    sırasıyla, kurallara uyan). Eklenen adları döndürür; commit etmez."""
    from app.memory.preferences import PreferenceService
    from app.memory.rules import MealRules
    from app.planner.candidate_selector import CandidateSelector
    from app.planner.scorer import CandidateScorer

    if session.meal_plan is None:
        return []
    db.flush()
    target = MealRules.from_db(db).weekly_meze_target(settings)
    current = weekly_items(session)
    if target <= len(current):
        return []
    base = settings.meal_slots[0] if settings.meal_slots else "dinner"
    hard = PreferenceService(db).hard_rules()
    pool = CandidateSelector(db).select(base, hard, session.week_start, course_role="meze")
    # Asıl mezeler önce; salatalar yalnızca meze yetmezse.
    pool = sorted(pool, key=lambda r: 0 if (r.category or "") == "meze" else 1)
    scored = CandidateScorer(db).score(pool, session.week_start, Counter())
    scored = sorted(scored, key=lambda r: 0 if (r.category or "") == "meze" else 1)
    used = {i.recipe_id for i in session.meal_plan.items}
    slots = {i.meal_slot for i in current}
    added: list[str] = []
    for recipe in scored:
        if len(current) + len(added) >= target:
            break
        if recipe.id in used:
            continue
        slot = next_weekly_slot(slots)
        slots.add(slot)
        used.add(recipe.id)
        session.meal_plan.items.append(MealPlanItem(date=session.week_start, meal_slot=slot, recipe_id=recipe.id))
        added.append(recipe.name)
    if added:
        db.flush()
        logger.info("weekly_mezes_added session_id=%s count=%s", session.id, len(added))
    return added
