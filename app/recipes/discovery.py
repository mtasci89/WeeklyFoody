from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, Field

from app.config import Settings
from app.llm.gemini import GeminiLLMProvider
from app.recipes.importer import RecipeInput


class RecipeDiscoveryProvider(Protocol):
    async def discover(self, query: str, limit: int = 5) -> list[RecipeInput]:
        ...


class NullRecipeDiscoveryProvider:
    async def discover(self, query: str, limit: int = 5) -> list[RecipeInput]:
        return []


class RecipeDiscoveryOutput(BaseModel):
    recipes: list[RecipeInput] = Field(default_factory=list)


class GeminiRecipeDiscoveryProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = GeminiLLMProvider(settings)

    async def discover(self, query: str, limit: int = 5) -> list[RecipeInput]:
        output = await self.llm._structured(
            "You discover practical family recipes for a Turkish-speaking household. Return candidate recipes only; do not claim they are from a specific website. Include structured ingredients with quantities where reasonable.",
            json.dumps(
                {
                    "query": query,
                    "limit": limit,
                    "requirements": [
                        "Use Turkish recipe names when appropriate.",
                        "Make recipes realistic for home cooking.",
                        "Set status to candidate.",
                        "Use meal_type dinner unless query clearly asks otherwise.",
                        "Include ingredients, quantities, units, servings, prep/cook times, instructions, tags, protein_type, vegetarian.",
                    ],
                },
                ensure_ascii=False,
            ),
            RecipeDiscoveryOutput,
        )
        recipes: list[RecipeInput] = []
        for recipe in output.recipes[:limit]:
            recipe.status = "candidate"
            recipe.source = recipe.source or f"gemini-discovery:{query[:80]}"
            recipe.tags = sorted(set([*(recipe.tags or []), "discovered"]))
            recipes.append(recipe)
        return recipes


def build_recipe_discovery_provider(settings: Settings) -> RecipeDiscoveryProvider:
    if settings.gemini_api_key:
        return GeminiRecipeDiscoveryProvider(settings)
    return NullRecipeDiscoveryProvider()
