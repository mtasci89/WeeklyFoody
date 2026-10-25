from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.config import Settings, base_meal_slot, course_role
from app.db.models import PreferenceType, WeeklyPlanningSession, SessionState
from app.llm import build_llm_provider
from app.memory.feedback import FeedbackService
from app.memory.preferences import PreferenceService
from app.planner.candidate_selector import CandidateSelector
from app.planner.dates import DAY_TO_INDEX, week_dates
from app.planner.service import plan_output, remember_published_plan
from app.planner.validator import PlanValidator
from app.recipes.service import RecipeService

logger = logging.getLogger(__name__)


class RevisionService:
    def __init__(self, db: Session, settings: Settings):
        self.db, self.settings = db, settings
        self.llm = build_llm_provider(settings)

    async def revise(self, session: WeeklyPlanningSession, message: str) -> WeeklyPlanningSession:
        if not session.meal_plan:
            raise ValueError("Değiştirilecek menü bulunamadı. Önce yeni menü oluştur.")
        expected_version = session.draft_version
        service = RecipeService(self.db)
        recipes = service.list_recipes()
        pending = (session.context or {}).get("pending_revision")
        request = f"{message}. {pending}" if pending else message
        context = {
            "recipes": [{"id": r.id, "name": r.name, "category": r.category, "meal_type": r.meal_type} for r in recipes],
            "current_plan": [{"date": i.date.isoformat(), "day_index": i.date.weekday(), "meal_slot": i.meal_slot, "recipe": i.recipe.name} for i in session.meal_plan.items],
            "hard_preferences": PreferenceService(self.db).hard_rules(),
        }
        revision = await self.llm.parse_revision(request, context)
        self.db.refresh(session)
        if session.draft_version != expected_version:
            raise ValueError("Menü bu sırada değişti. Son sürümü açıp isteğini tekrar gönder.")
        if revision.needs_clarification or not revision.operations:
            return self._clarify(session, revision.clarification_question or "Hangi gün ve yemeği değiştireyim?", request)
        # Resolve every operation before mutating anything: a failed request leaves the plan intact.
        changes = []
        hard_rules = PreferenceService(self.db).hard_rules()
        selector = CandidateSelector(self.db)
        for op in revision.operations:
            if op.date:
                target_date = date.fromisoformat(op.date)
            elif op.day_name and op.day_name.casefold() in DAY_TO_INDEX:
                target_date = session.week_start + timedelta(days=DAY_TO_INDEX[op.day_name.casefold()])
            else:
                return self._clarify(session, "Hangi günü değiştireyim? Örneğin: Çarşamba ana yemeği değiştir.", request)
            targets = [i for i in session.meal_plan.items if i.date == target_date]
            if op.meal_slot:
                targets = [i for i in targets if i.meal_slot == op.meal_slot or base_meal_slot(i.meal_slot) == op.meal_slot]
            if not targets:
                return self._clarify(session, "Bu gün veya öğün menüde yok. Menüdeki bir gün ve öğün seç.", request)
            if op.servings is not None:
                changes.extend((i, None, op.servings) for i in targets)
            food_targets = targets
            if op.exclude_recipe_name:
                food_targets = [i for i in targets if self._item_matches_text(i, op.exclude_recipe_name)]
                if not food_targets:
                    return self._clarify(session, "Bu günde belirttiğin yemeği bulamadım. Menüdeki yemek adını yazabilir misin?", request)
            replacement = service.find_recipe(op.recipe_name) if op.recipe_name else None
            if op.recipe_name and (replacement is None or replacement not in recipes):
                return self._clarify(session, f"{op.recipe_name} onaylı tarifler arasında yok. Önce tarifi ekle veya bir aday tarifi onayla.", request)
            if replacement:
                food_targets = [i for i in food_targets if selector._matches_course_role(replacement, course_role(i.meal_slot)) and replacement.meal_type == base_meal_slot(i.meal_slot)]
                if len(food_targets) != 1:
                    # A main/side is unique; two meze slots need an explicit existing dish name.
                    return self._clarify(session, "Hangi yemeğin yerine koyayım? Gün, mevcut yemek ve yeni yemek adını birlikte yaz.", request)
            elif op.exclude_recipe_name:
                pass
            elif op.servings is not None:
                continue
            else:
                return self._clarify(session, "Hangi yemeği değiştireyim? Örneğin: Salı balığı çıkar.", request)
            for item in food_targets:
                candidates = selector.select(base_meal_slot(item.meal_slot), hard_rules, session.week_start, recent_weeks=0, course_role=course_role(item.meal_slot))
                if replacement:
                    if replacement not in candidates:
                        raise ValueError("Bu tarif kalıcı tercihlerine veya öğün türüne uymuyor. Başka bir tarif seç.")
                    selected = replacement
                else:
                    same_day = {i.recipe_id for i in session.meal_plan.items if i.date == item.date}
                    selected = next((r for r in candidates if r.id not in same_day and not self._recipe_matches_text(r, op.exclude_recipe_name)), None)
                    if selected is None:
                        selected = next((r for r in candidates if r.id != item.recipe_id and not self._recipe_matches_text(r, op.exclude_recipe_name)), None)
                    if selected is None:
                        return self._clarify(session, "Tercihlerine uyan başka bir onaylı tarif yok. Önce bu kategoride bir tarif ekleyelim.", request)
                if selected.id != item.recipe_id:
                    changes.append((item, selected, None))
        if not any(r is not None or (s is not None and s != i.servings) for i, r, s in changes):
            return self._clarify(session, "Menü zaten bu şekilde; başka neyi değiştireyim?", request)
        try:
            remember_published_plan(session)
            for item, replacement, servings in changes:
                if servings is not None:
                    item.servings = servings
                if replacement:
                    original = item.recipe_id
                    item.original_recipe_id = item.original_recipe_id or original
                    item.recipe_id, item.recipe = replacement.id, replacement
                    item.admin_changed, item.change_reason = True, message
                    FeedbackService(self.db).record(message, session_id=session.id, original_recipe_id=original, replacement_recipe_id=replacement.id, context={"date": item.date.isoformat(), "meal_slot": item.meal_slot}, commit=False)
            PlanValidator(self.db).validate(plan_output(session), week_dates(session.week_start), self.settings.planning_slots, hard_rules)
            session.context = {k: v for k, v in (session.context or {}).items() if k not in {"pending_revision", "clarification"}}
            session.state, session.meal_plan.status = SessionState.AWAITING_APPROVAL, "draft"
            session.draft_version += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        logger.info("draft_revised session_id=%s version=%s", session.id, session.draft_version)
        return session

    def _clarify(self, session, question, request):
        session.context = {**(session.context or {}), "clarification": question, "pending_revision": request}
        self.db.commit()
        return session

    def _item_matches_text(self, item, text):
        return self._recipe_matches_text(item.recipe, text)

    def _recipe_matches_text(self, recipe, text):
        from app.llm.rule_based import _contains_term
        haystack = " ".join([recipe.name, recipe.protein_type or "", " ".join(recipe.tags or []), " ".join(i.ingredient.name for i in recipe.ingredients)]).casefold()
        return bool(text) and _contains_term(haystack, text.casefold())
