from __future__ import annotations

from typing import Any

from app.llm.base import Intent, IntentOutput, LLMProvider, PlannedMeal, PreferencePayload, RevisionOperation, RevisionOutput, WeeklyPlanOutput


class RuleBasedLLMProvider(LLMProvider):
    """Deterministic fallback for local operation and tests."""

    async def generate_plan(self, context: dict[str, Any]) -> WeeklyPlanOutput:
        candidates = context.get("candidate_recipes", [])
        slots = context.get("meal_slots", ["dinner"])
        dates = context.get("dates", [])
        meals: list[PlannedMeal] = []
        idx = 0
        for date_value in dates:
            for slot in slots:
                if not candidates:
                    continue
                recipe = candidates[idx % len(candidates)]
                meals.append(
                    PlannedMeal(
                        date=date_value,
                        meal_slot=slot,
                        recipe_id=recipe["id"],
                        servings=context.get("serving_overrides", {}).get(date_value),
                    )
                )
                idx += 1
        return WeeklyPlanOutput(meals=meals, notes="Kural tabanlı yedek plan.")

    async def route_intent(self, message: str, context: dict[str, Any] | None = None) -> IntentOutput:
        text = message.casefold().strip()
        if "/approve" in text or any(word in text for word in ("onaylıyorum", "onayla", "tamamdır", "bu liste iyi", "güzel oldu")):
            return IntentOutput(intent=Intent.APPROVE_PLAN, confidence=0.95, raw_request=message)
        if "/regenerate" in text or "yeniden" in text or "baştan" in text:
            return IntentOutput(intent=Intent.REGENERATE_PLAN, confidence=0.9, raw_request=message)
        if "/shopping" in text or "alışveriş" in text:
            return IntentOutput(intent=Intent.SHOW_SHOPPING_LIST, confidence=0.9, raw_request=message)
        if "/menu" in text or "menü" in text or "listeyi göster" in text:
            return IntentOutput(intent=Intent.SHOW_MENU, confidence=0.8, raw_request=message)
        if "/recipes" in text or "tarifler" in text:
            return IntentOutput(intent=Intent.SHOW_RECIPE if "/recipe " in text else Intent.GENERAL_QUESTION, confidence=0.75, raw_request=message)
        if "/addrecipe" in text or "bu tarifi kaydet" in text:
            return IntentOutput(intent=Intent.ADD_RECIPE, confidence=0.9, recipe_text=message, raw_request=message)
        if "bundan sonra" in text or "/addpreference" in text or "artık" in text:
            return IntentOutput(
                intent=Intent.ADD_PREFERENCE,
                confidence=0.8,
                preference=PreferencePayload(type="hard", rule=message.replace("/addpreference", "").strip()),
                raw_request=message,
            )
        if "/pantryadd" in text or "evde var" in text:
            return IntentOutput(intent=Intent.ADD_PANTRY_ITEM, confidence=0.8, pantry_item=message.replace("/pantryadd", "").strip(), raw_request=message)
        if any(word in text for word in ("değiştir", "olmasın", "koy", "çıkar", "kişi olacağız", "yemeyeceğiz", "dışarıda")):
            return IntentOutput(intent=Intent.MODIFY_PLAN, confidence=0.82, raw_request=message)
        return IntentOutput(intent=Intent.UNKNOWN, confidence=0.2, raw_request=message)

    async def parse_revision(self, message: str, context: dict[str, Any] | None = None) -> RevisionOutput:
        text = message.casefold()
        operations: list[RevisionOperation] = []
        days = {
            "pazartesi": "monday",
            "salı": "tuesday",
            "çarşamba": "wednesday",
            "perşembe": "thursday",
            "cuma": "friday",
            "cumartesi": "saturday",
            "pazar": "sunday",
        }
        known_recipes = [r["name"] for r in (context or {}).get("recipes", [])]
        for tr_day, en_day in days.items():
            if tr_day in text:
                servings = None
                if "kişi" in text:
                    for token in text.replace(".", " ").split():
                        if token.isdigit():
                            servings = int(token)
                            break
                recipe_name = None
                for known in known_recipes:
                    if known.casefold() in text:
                        recipe_name = known
                        break
                if recipe_name or servings or any(word in text for word in ("dışarıda", "yemeyeceğiz")):
                    operations.append(
                        RevisionOperation(
                            day_name=en_day,
                            recipe_name=recipe_name,
                            servings=servings,
                            instruction=message,
                        )
                    )
        if not operations:
            operations.append(RevisionOperation(instruction=message))
        return RevisionOutput(operations=operations)

