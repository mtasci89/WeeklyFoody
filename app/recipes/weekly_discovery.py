from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Recipe
from app.recipes.discovery import build_recipe_discovery_provider
from app.recipes.importer import RecipeInput
from app.recipes.service import RecipeService

logger = logging.getLogger(__name__)


class WeeklyRecipeDiscoveryService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.recipe_service = RecipeService(db)

    async def discover_candidates(self) -> list[Recipe]:
        if not self.settings.recipe_discovery_enabled:
            return []
        provider = build_recipe_discovery_provider(self.settings)
        discovered: list[Recipe] = []
        for query in self.settings.recipe_discovery_queries:
            recipes = await provider.discover(query, limit=self.settings.recipe_discovery_limit_per_category)
            for recipe_input in recipes:
                normalized = self._normalize(recipe_input, query)
                recipe = self.recipe_service.upsert_recipe(normalized)
                if recipe not in discovered:
                    discovered.append(recipe)
        logger.info("recipe_discovery_completed candidates=%s", len(discovered))
        return discovered

    def _normalize(self, recipe: RecipeInput, query: str) -> RecipeInput:
        recipe.status = "candidate"
        recipe.meal_type = "dinner"
        recipe.source = recipe.source or f"weekly-discovery:{query[:80]}"
        recipe.tags = sorted(set([*(recipe.tags or []), "discovered", "weekly-discovery"]))
        forced_category = self._category_from_query(query)
        if forced_category:
            recipe.category = forced_category
        elif recipe.category not in {"main", "side", "soup", "grain", "pasta", "pilaf", "meze", "salad"}:
            recipe.category = "main"
        return recipe

    def _category_from_query(self, query: str) -> str | None:
        lower = query.casefold()
        if "category=main" in lower or "ana yemek" in lower:
            return "main"
        if "category=side" in lower or "yan yemek" in lower:
            return "side"
        if "category=meze" in lower or "meze" in lower:
            return "meze"
        if "category=salad" in lower or "salata" in lower:
            return "salad"
        return None
