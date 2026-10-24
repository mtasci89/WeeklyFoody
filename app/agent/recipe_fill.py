"""Malzemesi kaydedilmemiş tarifleri tamamlamak.

Kütüphanenin çoğu eski menü Excel'inden yalnızca adlarıyla geldi ("ingredients can be
taught later"). Bu tarifler menüye girince uygulamada boş görünüyor ve alışveriş
listesine hiçbir şey eklemiyordu. Menüye giren boş tarifler tek bir yapılandırılmış
istekte (en fazla 6'şar) model tarafından yazılır ve kaydedilir; her tarif bir kez.
"""
from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

BATCH = 6
# Uygulama tarifleri ve alışverişi aynı anda ister: aynı tarif iki kez yazılmasın.
_LOCK = asyncio.Lock()
NOTE = "Malzemeler ve hazırlanış yapay zekâ ile tamamlandı; dilersen düzenle."

SCHEMA = {
    "type": "object",
    "properties": {
        "tarifler": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ad": {"type": "string"},
                    "porsiyon": {"type": "integer"},
                    "malzemeler": {"type": "array", "items": {"type": "string"}},
                    "hazirlanis": {"type": "string"},
                    "hazirlik_dakika": {"type": "integer"},
                    "pisirme_dakika": {"type": "integer"},
                },
                "required": ["ad", "malzemeler", "hazirlanis"],
            },
        }
    },
    "required": ["tarifler"],
}


def needs_filling(recipe) -> bool:
    return not recipe.ingredients


def prompt_for(recipes) -> str:
    names = "\n".join(f"- {r.name}" + (f" ({r.category})" if r.category else "") for r in recipes)
    return (
        "Aşağıdaki ev yemeklerinin her biri için Türk ev mutfağındaki en yaygın, evde yapılan "
        "tarifi yaz. Adı AYNEN yaz. 4 kişilik olsun. Malzemeleri ayrı satırlarda miktarıyla yaz "
        "('500 gr kırmızı mercimek', '1 adet soğan', '2 yemek kaşığı tereyağı', 'tuz'). "
        "Hazırlanışı 3-7 kısa adımda yaz. Yemeği değiştirme, yorum katma.\n\n" + names
    )


async def fill_recipes(db, ask_json, recipes) -> list[str]:
    """Malzemesi olmayan tarifleri tamamlar; tamamlananların adlarını döndürür."""
    if ask_json is None:
        return []
    if not any(r is not None and needs_filling(r) for r in recipes):
        return []
    async with _LOCK:
        return await _fill(db, ask_json, recipes)


async def _fill(db, ask_json, recipes) -> list[str]:
    from app.agent.tools import parse_ingredient
    from app.recipes.importer import RecipeInput
    from app.recipes.service import RecipeService

    seen, targets = set(), []
    for recipe in recipes:
        if recipe is None or recipe.id in seen:
            continue
        seen.add(recipe.id)
        db.refresh(recipe)  # başka bir istek az önce tamamlamış olabilir
        if needs_filling(recipe):
            targets.append(recipe)
    done: list[str] = []
    service = RecipeService(db)
    for start in range(0, len(targets), BATCH):
        chunk = targets[start:start + BATCH]
        try:
            data = json.loads(await ask_json(prompt_for(chunk), SCHEMA))
        except Exception:
            logger.exception("recipe_fill_failed count=%s", len(chunk))
            continue
        by_name = {r.name.casefold(): r for r in chunk}
        for row in data.get("tarifler", []) if isinstance(data, dict) else []:
            recipe = by_name.get(str(row.get("ad", "")).strip().casefold())
            lines = [str(x).strip() for x in row.get("malzemeler") or [] if str(x).strip()]
            if recipe is None or len(lines) < 2 or not needs_filling(recipe):
                continue
            service.upsert_recipe(
                RecipeInput(
                    name=recipe.name,
                    aliases=list(recipe.aliases or []),
                    cuisine=recipe.cuisine,
                    category=recipe.category or "main",
                    meal_type=recipe.meal_type or "dinner",
                    servings=max(1, int(row.get("porsiyon") or 4)),
                    ingredients=[parse_ingredient(line) for line in lines],
                    instructions=(recipe.instructions or str(row.get("hazirlanis") or "").strip()) or None,
                    prep_minutes=recipe.prep_minutes or (int(row.get("hazirlik_dakika") or 0) or None),
                    cook_minutes=recipe.cook_minutes or (int(row.get("pisirme_dakika") or 0) or None),
                    tags=list(recipe.tags or []),
                    protein_type=recipe.protein_type,
                    vegetarian=bool(recipe.vegetarian),
                    seasonal=list(recipe.seasonal or []),
                    source=recipe.source,
                    notes=NOTE,
                    status=recipe.status.value,
                )
            )
            done.append(recipe.name)
    if done:
        logger.info("recipes_filled count=%s", len(done))
    return done
