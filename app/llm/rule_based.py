from __future__ import annotations

from typing import Any

from app.llm.base import Intent, IntentOutput, LLMProvider, PlannedMeal, PreferencePayload, RevisionOperation, RevisionOutput, WeeklyPlanOutput


class RuleBasedLLMProvider(LLMProvider):
    """Deterministic fallback for local operation and tests."""

    async def generate_plan(self, context: dict[str, Any]) -> WeeklyPlanOutput:
        candidates = context.get("candidate_recipes", [])
        candidates_by_slot = context.get("candidate_recipes_by_slot", {})
        slots = context.get("meal_slots", ["dinner"])
        dates = context.get("dates", [])
        if context.get("max_kcal_per_meal") is not None or context.get("distinct_dishes") or context.get("protein_priority"):
            return constrained_plan(context)
        meals: list[PlannedMeal] = []
        slot_indexes = {slot: 0 for slot in slots}
        for date_value in dates:
            used_recipe_ids: set[str] = set()
            for slot in slots:
                slot_candidates = candidates_by_slot.get(slot) or candidates
                if not slot_candidates:
                    continue
                slot_index = slot_indexes.get(slot, 0)
                recipe = slot_candidates[slot_index % len(slot_candidates)]
                if recipe["id"] in used_recipe_ids:
                    recipe = next((candidate for candidate in slot_candidates if candidate["id"] not in used_recipe_ids), recipe)
                meals.append(
                    PlannedMeal(
                        date=date_value,
                        meal_slot=slot,
                        recipe_id=recipe["id"],
                        servings=context.get("serving_overrides", {}).get(date_value),
                    )
                )
                used_recipe_ids.add(recipe["id"])
                slot_indexes[slot] = slot_index + 1
        return WeeklyPlanOutput(meals=meals, notes="Kural tabanlı yedek plan.")

    async def route_intent(self, message: str, context: dict[str, Any] | None = None) -> IntentOutput:
        text = message.casefold().strip()
        if _looks_like_recipe_text(message):
            return IntentOutput(intent=Intent.ADD_RECIPE, confidence=0.92, recipe_text=message, raw_request=message)
        if "/approve" in text or any(word in text for word in ("onaylıyorum", "onayla", "tamamdır", "bu liste iyi", "güzel oldu")):
            return IntentOutput(intent=Intent.APPROVE_PLAN, confidence=0.95, raw_request=message)
        if "/regenerate" in text or "yeniden" in text or "baştan" in text:
            return IntentOutput(intent=Intent.REGENERATE_PLAN, confidence=0.9, raw_request=message)
        if "/candidates" in text or "aday tarif" in text:
            return IntentOutput(intent=Intent.SHOW_RECIPE_CANDIDATES, confidence=0.9, raw_request=message)
        if "/approverecipe" in text or "bu tarifi tariflerime ekle" in text or "adayı onayla" in text:
            name = message.replace("/approverecipe", "").replace("bu tarifi tariflerime ekle", "").replace("adayı onayla", "").strip()
            return IntentOutput(intent=Intent.APPROVE_RECIPE_CANDIDATE, confidence=0.85, recipe_name=name or None, raw_request=message)
        if "/addrecipe" in text or "bu tarifi kaydet" in text or any(phrase in text for phrase in ("tarif ekle", "tarifi ekle", "yemek ekle", "tarif kaydet")):
            return IntentOutput(intent=Intent.ADD_RECIPE, confidence=0.92, recipe_text=message if _has_recipe_details(message) else None, raw_request=message)
        if "/discover" in text or any(word in text for word in ("bul", "öner", "keşfet", "ara")) and any(word in text for word in ("tarif", "yemek", "yemeği")) or "farklı şeyler öner" in text:
            query = message.replace("/discover", "").strip()
            return IntentOutput(intent=Intent.DISCOVER_RECIPE, confidence=0.82, discovery_query=query or message, raw_request=message)
        if "/shopping" in text or "alışveriş" in text:
            return IntentOutput(intent=Intent.SHOW_SHOPPING_LIST, confidence=0.9, raw_request=message)
        if "/menu" in text or "menü" in text or "listeyi göster" in text:
            return IntentOutput(intent=Intent.SHOW_MENU, confidence=0.8, raw_request=message)
        if "/recipes" in text or "tarifler" in text:
            return IntentOutput(intent=Intent.SHOW_RECIPE if "/recipe " in text else Intent.GENERAL_QUESTION, confidence=0.75, raw_request=message)
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
        if "?" in text or any(word in text for word in ("nasıl", "nedir", "ne yap", "yardım", "hangi", "kaç", "kim")):
            return IntentOutput(intent=Intent.GENERAL_QUESTION, confidence=0.7, raw_request=message)
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
        recipe_terms = _recipe_terms(known_recipes)
        day_hits = sorted((text.find(tr_day), tr_day, en_day) for tr_day, en_day in days.items() if tr_day in text)
        for tr_day, en_day in days.items():
            if tr_day in text:
                segment = _day_segment(text, tr_day, day_hits)
                servings = None
                if "kişi" in segment:
                    for token in segment.replace(".", " ").split():
                        if token.isdigit():
                            servings = int(token)
                            break
                recipe_name = None
                for known in known_recipes:
                    if known.casefold() in segment:
                        recipe_name = known
                        break
                exclude_recipe_name = None
                if any(word in segment for word in ("olmasın", "çıkar", "değiştir", "yemeyelim")):
                    for term in recipe_terms:
                        if _contains_term(segment, term):
                            exclude_recipe_name = term
                            break
                if recipe_name or exclude_recipe_name or servings or any(word in segment for word in ("dışarıda", "yemeyeceğiz")):
                    operations.append(
                        RevisionOperation(
                            day_name=en_day,
                            recipe_name=recipe_name,
                            exclude_recipe_name=exclude_recipe_name,
                            servings=servings,
                            instruction=message,
                        )
                    )
        if not operations:
            operations.append(RevisionOperation(instruction=message))
        return RevisionOutput(operations=operations)

    async def answer_general_question(self, message: str, context: dict[str, Any] | None = None) -> str:
        text = message.casefold()
        if "tarif" in text and "ekle" in text:
            return "Yeni tarif eklemek için tarifin adını ve malzemelerini yazabilirsin. Örn:\n\nTavuk Fajita\n600 gr tavuk\n2 biber\n1 soğan"
        if "ne yap" in text or "yardım" in text or "komut" in text:
            return (
                "Ben haftalık yemek planı hazırlayabilir, menüyü konuşarak revize edebilir, tarif ve tercih hafızası tutabilir, "
                "onaydan sonra alışveriş listesi çıkarabilirim. Örn: `Salı balık olmasın`, `yeni tavuk yemeği bul`, "
                "`bu tarifi kaydet:` diye yazabilirsin."
            )
        return "Yemek planı, tarifler, tercihler ve alışveriş listesi hakkında yardımcı olabilirim. Bir işlem yapmak istersen doğal dille yazman yeterli."


def _recipe_terms(recipe_names: list[str]) -> list[str]:
    terms = {"balık", "tavuk", "köfte", "fasulye", "makarna", "nohut", "çorba", "pilav"}
    for name in recipe_names:
        lowered = name.casefold()
        terms.add(lowered)
        terms.update(part for part in lowered.split() if len(part) > 3)
    return sorted(terms, key=len, reverse=True)


def _day_segment(text: str, tr_day: str, day_hits: list[tuple[int, str, str]]) -> str:
    start = text.find(tr_day)
    end = len(text)
    for hit_start, _, _ in day_hits:
        if hit_start > start:
            end = hit_start
            break
    return text[start:end]


def _contains_term(text: str, term: str) -> bool:
    variants = {term}
    if term.endswith("k"):
        variants.add(f"{term[:-1]}ğ")
    if term.endswith("t"):
        variants.add(f"{term[:-1]}d")
    variants.add(term.rstrip("k"))
    return any(variant and variant in text for variant in variants)


def _has_recipe_details(message: str) -> bool:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    units = ("gr", "g", "gram", "kg", "ml", "l", "lt", "adet", "paket", "demet", "kaşığı", "bardak")
    ingredient_like = 0
    for line in lines[1:]:
        lowered = line.casefold()
        if any(char.isdigit() for char in lowered) or any(unit in lowered.split() for unit in units):
            ingredient_like += 1
    return ingredient_like >= 1


def _looks_like_recipe_text(message: str) -> bool:
    text = message.casefold()
    return _has_recipe_details(message) and not text.startswith("/") and not any(
        phrase in text for phrase in ("menüyü", "menü", "alışveriş", "pantry", "tercih")
    )


def constrained_plan(context: dict[str, Any]) -> WeeklyPlanOutput:
    """Bounded per-meal search over the scored candidate pool."""
    from collections import defaultdict
    from app.config import base_meal_slot
    from app.memory.rules import RuleViolation

    cap = context.get("max_kcal_per_meal")
    slots_by_meal = defaultdict(list)
    for slot in context["meal_slots"]:
        slots_by_meal[base_meal_slot(slot)].append(slot)
    meals = []
    for day_index, day in enumerate(context["dates"]):
        for base, slots in slots_by_meal.items():
            pools = []
            for slot in slots:
                choices = list(context["candidate_recipes_by_slot"].get(slot, []))
                if cap is not None:
                    choices = [r for r in choices if r.get("calories_kcal") is not None]
                if not choices:
                    raise RuleViolation(f"{day} {slot}: uygun tarif yok veya kalori verisi eksik. Tarif bilgilerini tamamlayın.")
                if not context.get("protein_priority"):
                    shift = day_index % len(choices)
                    choices = choices[shift:] + choices[:shift]
                pools.append(choices)
            visited = 0

            def search(index, selected, used, energy):
                nonlocal visited
                visited += 1
                if visited > 20000:
                    raise RuleViolation("Uygun öğün arama sınırına ulaşıldı; adayları veya kuralları gözden geçirin.")
                if index == len(slots):
                    return selected
                if cap is not None:
                    lower_bound = sum(min(r["calories_kcal"] for r in pool) for pool in pools[index:])
                    if energy + lower_bound > cap:
                        return None
                for recipe in pools[index]:
                    if recipe["id"] in used:
                        continue
                    kcal = recipe.get("calories_kcal") or 0
                    if cap is not None and energy + kcal > cap:
                        continue
                    found = search(index + 1, selected + [recipe], used | {recipe["id"]}, energy + kcal)
                    if found is not None:
                        return found
                return None

            selected = search(0, [], set(), 0)
            if selected is None:
                raise RuleViolation(f"{day} {base}: aday havuzunda yemek sayısı/kalori kurallarına uygun bir öğün bulunamadı.")
            for slot, recipe in zip(slots, selected):
                meals.append(PlannedMeal(date=day, meal_slot=slot, recipe_id=recipe["id"], servings=context.get("serving_overrides", {}).get(day)))
    return WeeklyPlanOutput(meals=meals, notes="Kalıcı kurallarla denetlenmiş kural tabanlı plan.")
