from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from app.recipes.nutrition import NutritionInput, save_nutrition

logger = logging.getLogger(__name__)

ESTIMATE_SOURCE = "otomatik tahmin (malzemelerden)"
BATCH = 25

SCHEMA = {
    "type": "object",
    "properties": {
        "tarifler": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ad": {"type": "string"},
                    "kcal": {"type": "number"},
                    "protein_g": {"type": "number"},
                },
                "required": ["ad", "kcal", "protein_g"],
            },
        }
    },
    "required": ["tarifler"],
}

# (istem, sema) -> JSON metni. Gercekte GeminiBackend.generate_json.
AskJson = Callable[[str, dict], Awaitable[str]]


def _recipe_block(recipe) -> str:
    lines = [f"### {recipe.name} ({recipe.servings} porsiyon)"]
    for ing in recipe.ingredients:
        qty = f"{ing.quantity:g} {ing.unit or ''}".strip() if ing.quantity is not None else "biraz"
        lines.append(f"- {qty} {ing.ingredient.name}")
    return "\n".join(lines)


class NutritionEstimator:
    """Kalori/protein degeri olmayan tarifleri tek istekte tahmin edip kaydeder.

    Kullanici "kalorileri yaz" dedikce ajanin her tarif icin ayrica
    `besin_degeri_kaydet` cagirmasini beklemek guvenilir degildi (zayif yedek
    model bunu atliyordu). Kural kalori istiyorsa sistem eksikleri kendisi
    doldurur; degerler tahmini olarak isaretlenir, elle girilmis degerlere
    dokunulmaz.
    """

    def __init__(self, ask_json: AskJson):
        self.ask_json = ask_json

    async def fill_missing(self, db, recipes) -> list[str]:
        missing, seen = [], set()
        for recipe in recipes:
            if recipe.id in seen:
                continue
            seen.add(recipe.id)
            if recipe.nutrition is None or recipe.nutrition.calories_kcal is None:
                missing.append(recipe)
        saved: list[str] = []
        for start in range(0, len(missing), BATCH):
            saved += await self._estimate(db, missing[start:start + BATCH])
        if saved:
            db.commit()
            logger.info("nutrition_estimated count=%s", len(saved))
        return saved

    async def _estimate(self, db, recipes) -> list[str]:
        prompt = (
            "Aşağıdaki ev yemeği tariflerinin BİR PORSİYONUNUN (tarifin toplamı / "
            "porsiyon sayısı) yaklaşık kalorisini (kcal) ve protein gramını "
            "malzemelere bakarak tahmin et. Her tarifin adını aynen yaz.\n\n"
            + "\n\n".join(_recipe_block(r) for r in recipes)
        )
        try:
            data = json.loads(await self.ask_json(prompt, SCHEMA))
        except Exception:
            logger.exception("nutrition_estimate_failed count=%s", len(recipes))
            return []
        by_name = {r.name.casefold(): r for r in recipes}
        saved = []
        for row in data.get("tarifler", []) if isinstance(data, dict) else []:
            recipe = by_name.get(str(row.get("ad", "")).strip().casefold())
            try:
                kcal = round(float(row.get("kcal")))
                protein = round(float(row.get("protein_g")))
            except (TypeError, ValueError):
                continue
            if recipe is None or not 20 <= kcal <= 3000 or not 0 <= protein <= 250:
                continue
            if recipe.nutrition is not None and not recipe.nutrition.estimated:
                continue
            save_nutrition(
                db,
                recipe,
                NutritionInput(calories_kcal=kcal, protein_g=protein, source=ESTIMATE_SOURCE, estimated=True),
            )
            saved.append(recipe.name)
        return saved


async def fill_for_rules(db, settings, recipes, *, library: bool = False) -> list[str]:
    """Kurallar kalori istiyorsa eksik degerleri doldurur; ajan disindaki yollar
    (/menu, /regenerate, haftalik plan) icin.

    `library=True`: otomatik planlayici kalori siniri varken degeri olmayan
    tarifleri aday havuzundan atiyor; bu yuzden sinir varsa tum kutuphane
    onceden doldurulur. Yalnizca gosterim kurali icin plan yeterli.
    """
    from app.memory.rules import MealRules

    rules = MealRules.from_db(db)
    needed = rules.max_kcal is not None if library else (rules.show_calories or rules.max_kcal is not None)
    if not needed or not settings.gemini_api_key:
        return []
    from app.agent.gemini_backend import GeminiBackend

    backend = GeminiBackend(settings)
    try:
        return await NutritionEstimator(backend.generate_json).fill_missing(db, recipes)
    finally:
        await backend.client.aio.aclose()
