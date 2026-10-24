"""Haftalık menüye kütüphane dışından yeni yemek katmak.

"Yeni yemek" = henüz onaylanmamış (aday) tarif. Ajan ya da haftalık keşif onu
kaydeder, menüye "yeni" diye girer; aile beğenirse onaylanıp kütüphaneye geçer.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import WEEKLY_BASE, Settings, course_role, is_weekly_slot
from app.db.models import MealPlanItem, Recipe, RecipeStatus, WeeklyPlanningSession

logger = logging.getLogger(__name__)

# Yeni yemekler haftaya yayılsın: önce Çarşamba, Cuma, Pazar...
DAY_ORDER = (2, 4, 6, 1, 3, 5, 0)


def is_new(recipe: Recipe) -> bool:
    return recipe.status == RecipeStatus.CANDIDATE


def untried_candidates(db: Session, rules=None) -> list[Recipe]:
    """Hiçbir menüye girmemiş aday tarifler, en yenisi önce."""
    used = set(db.scalars(select(MealPlanItem.recipe_id)))
    rows = db.scalars(
        select(Recipe).where(Recipe.status == RecipeStatus.CANDIDATE).order_by(Recipe.created_at.desc())
    )
    return [r for r in rows if r.id not in used and not (rules and rules.excludes(r))]


async def add_new_dishes(db: Session, settings: Settings, session: WeeklyPlanningSession) -> list[str]:
    """Otomatik planlayıcının taslağına, hedef sayıya kadar denenmemiş aday
    tarifleri koyar (aynı rolde bir öğünün yerine). Kurallara aykırı düşen
    değişiklik yapılmaz. Eklenen tariflerin adlarını döndürür; commit etmez."""
    from app.memory.rules import MealRules, RuleViolation

    if not session.meal_plan or not session.meal_plan.items:
        return []
    db.flush()  # yeni eklenen öğünlerin tarifleri yüklenebilsin
    rules = MealRules.from_db(db)
    items = list(session.meal_plan.items)
    missing = rules.new_dish_target(settings) - sum(1 for i in items if is_new(i.recipe))
    pool = untried_candidates(db, rules)
    if missing <= 0 or not pool:
        return []
    if rules.max_kcal is not None:
        from app.agent.nutrition import fill_for_rules

        await fill_for_rules(db, settings, pool)

    from app.planner.candidate_selector import CandidateSelector

    selector = CandidateSelector(db)
    def key(item):
        # Haftalık meze listesi kendi başına bir "gün" sayılır.
        return WEEKLY_BASE if is_weekly_slot(item.meal_slot) else item.date

    days = sorted({i.date for i in items if not is_weekly_slot(i.meal_slot)})
    order = [days[k] for k in DAY_ORDER if k < len(days)]
    if any(is_weekly_slot(i.meal_slot) for i in items):
        order.append(WEEKLY_BASE)
    added: list[str] = []
    for recipe in pool:
        if len(added) >= missing:
            break
        busy = {key(i) for i in items if is_new(i.recipe)}
        for day in order:
            if day in busy:
                continue
            slot_item = next(
                (
                    i for i in sorted(items, key=lambda i: i.meal_slot)
                    if key(i) == day and selector._matches_course_role(recipe, course_role(i.meal_slot))
                ),
                None,
            )
            if slot_item is None:
                continue
            rows = [(i.date, i.meal_slot, recipe if i is slot_item else i.recipe) for i in items]
            try:
                rules.validate(rows)
            except RuleViolation:
                continue
            slot_item.recipe_id = recipe.id
            slot_item.recipe = recipe
            slot_item.change_reason = "Haftanın yeni yemeği"
            added.append(recipe.name)
            break
    if added:
        db.flush()
        logger.info("new_dishes_added session_id=%s count=%s", session.id, len(added))
    return added
