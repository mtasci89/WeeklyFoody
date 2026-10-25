from __future__ import annotations

import re

from typing import Any

from app.llm.base import Intent, IntentOutput, LLMProvider, PlannedMeal, PreferencePayload, RevisionOperation, RevisionOutput, WeeklyPlanOutput


class RuleBasedLLMProvider(LLMProvider):
    """Deterministic fallback for local operation and tests."""

    async def generate_plan(self, context: dict[str, Any]) -> WeeklyPlanOutput:
        candidates = context.get("candidate_recipes", [])
        candidates_by_slot = context.get("candidate_recipes_by_slot", {})
        slots = context.get("meal_slots", ["dinner"])
        dates = context.get("dates", [])
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
        text = message.casefold().strip().rstrip(".! ")
        def result(intent, **kwargs):
            return IntentOutput(intent=intent, confidence=0.95, raw_request=message, **kwargs)
        if re.search(r"\bonaylama(?:yacağım|dım|yın)?\b|\bonaylamıyorum\b|\bonay verme\b", text):
            return result(Intent.GENERAL_QUESTION)
        if "adayı onayla" in text or "bu tarifi tariflerime ekle" in text or text.startswith("/approverecipe"):
            name = re.sub(r"/approverecipe|bu tarifi tariflerime ekle|adayı onayla", "", message, flags=re.I).strip()
            return result(Intent.APPROVE_RECIPE_CANDIDATE, recipe_name=name or None)
        if text in {"onayla", "onaylıyorum", "menüyü onayla", "menüyü onaylıyorum", "bu menüyü onayla", "/approve", "tamamdır", "bu liste iyi", "güzel oldu"}:
            return result(Intent.APPROVE_PLAN)
        if text.startswith("/regenerate") or any(w in text for w in ("yeniden oluştur", "yeniden hazırla", "baştan oluştur", "baştan hazırla")):
            return result(Intent.REGENERATE_PLAN)
        if text.startswith("/candidates") or "aday tarif" in text:
            return result(Intent.SHOW_RECIPE_CANDIDATES)
        if text.startswith("/addrecipe") or "bu tarifi kaydet" in text or any(w in text for w in ("tarif ekle", "tarifi ekle", "yemek ekle", "tarif kaydet")):
            return result(Intent.ADD_RECIPE, recipe_text=message if _has_recipe_details(message) else None)
        if any(w in text for w in ("bundan sonra", "artık")) or text.startswith("/addpreference"):
            return result(Intent.ADD_PREFERENCE, preference=PreferencePayload(rule=message.replace("/addpreference", "").strip()))
        if _looks_like_recipe_text(message):
            return result(Intent.ADD_RECIPE, recipe_text=message)
        if any(w in text for w in ("değiştir", "olmasın", "koy", "çıkar", "kişi olacağız", "kişiyiz", "yemeyeceğiz", "dışarıda", "yerine")):
            return result(Intent.MODIFY_PLAN)
        if text.startswith("/discover") or (any(w in text for w in ("bul", "öner", "keşfet", "ara")) and any(w in text for w in ("tarif", "yemek", "yemeği"))) or "farklı şeyler öner" in text:
            return result(Intent.DISCOVER_RECIPE, discovery_query=message.replace("/discover", "").strip())
        if text.startswith("/shopping") or "alışveriş" in text:
            return result(Intent.SHOW_SHOPPING_LIST)
        if text.startswith("/menu") or "menü" in text or "listeyi göster" in text:
            return result(Intent.SHOW_MENU)
        if text.startswith("/recipe "):
            return result(Intent.SHOW_RECIPE, recipe_name=message.split(" ", 1)[1])
        if "tercihler" in text or text == "/preferences":
            return result(Intent.SHOW_PREFERENCES)
        if text.startswith("/pantryadd") or "evde var" in text:
            return result(Intent.ADD_PANTRY_ITEM, pantry_item=message.replace("/pantryadd", "").replace("evde var", "").strip())
        if "?" in text or any(w in text for w in ("nasıl", "nedir", "ne yap", "yardım", "hangi", "kaç", "tarifler")):
            return IntentOutput(intent=Intent.GENERAL_QUESTION, confidence=0.7, raw_request=message)
        return IntentOutput(intent=Intent.UNKNOWN, confidence=0.2, raw_request=message)

    async def parse_revision(self, message: str, context: dict[str, Any] | None = None) -> RevisionOutput:
        text = message.casefold()
        days = {"pazartesi": "monday", "salı": "tuesday", "çarşamba": "wednesday", "perşembe": "thursday", "cuma": "friday", "cumartesi": "saturday", "pazar": "sunday"}
        day_pattern = r"\b(" + "|".join(sorted(days, key=len, reverse=True)) + r")(?:['’]?(?:ya|ye|yı|yi|yü|yu|da|de|dan|den|nın|nin|nun|nün|daki|deki|ki|kü))?\b"
        hits = list(re.finditer(day_pattern, text))
        if not hits:
            return RevisionOutput(needs_clarification=True, clarification_question="Hangi günü değiştireyim? Örneğin: Salı balık yerine Kuru Fasulye koy.")
        recipes = (context or {}).get("recipes", [])
        operations = []
        for index, hit in enumerate(hits):
            segment = text[hit.end():hits[index + 1].start() if index + 1 < len(hits) else len(text)]
            if any(w in segment for w in ("dışarıda", "yemeyeceğiz")):
                return RevisionOutput(needs_clarification=True, clarification_question="Bu günün öğününü kaldırma henüz desteklenmiyor. Yerine daha hafif bir yemek seçelim mi?")
            serving_match = re.search(r"\b(\d+)\s*kişi", segment)
            servings = int(serving_match.group(1)) if serving_match else None
            if servings is not None and not 1 <= servings <= 100:
                return RevisionOutput(needs_clarification=True, clarification_question="Kişi sayısı 1 ile 100 arasında olmalı. Kaç kişi olacaksınız?")
            removal = any(w in segment for w in ("olmasın", "çıkar", "değiştir", "yemeyelim"))
            replacement_text = segment.split("yerine", 1)[-1] if "yerine" in segment else segment
            recipe_name = next((r["name"] for r in sorted(recipes, key=lambda r: len(r["name"]), reverse=True) if r["name"].casefold() in replacement_text), None)
            if removal and "yerine" not in segment and not any(w in segment for w in ("koy", "ekle")):
                recipe_name = None
            exclude = None
            if removal or "yerine" in segment:
                source = segment.split("yerine", 1)[0]
                exclude = next((term for term in _recipe_terms([r["name"] for r in recipes]) if _contains_term(source, term)), None)
            if not recipe_name and not exclude and servings is None:
                return RevisionOutput(needs_clarification=True, clarification_question="Hangi yemeği değiştireyim? Gün ve yemek adı yazabilirsin: Salı balığı çıkar.")
            operations.append(RevisionOperation(day_name=days[hit.group(1)], recipe_name=recipe_name, exclude_recipe_name=exclude, servings=servings))
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
    first_line = text.splitlines()[0] if text.splitlines() else ""
    mentions_day = re.search(r"\b(?:pazartesi|cumartesi|çarşamba|perşembe|salı|cuma|pazar)\w*", first_line)
    return _has_recipe_details(message) and not mentions_day and not text.startswith("/") and not any(
        phrase in text for phrase in ("menüyü", "menü", "alışveriş", "pantry", "tercih")
    )

