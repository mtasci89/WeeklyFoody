from __future__ import annotations

from typing import Protocol

from app.recipes.importer import RecipeInput


class RecipeDiscoveryProvider(Protocol):
    async def discover(self, query: str, limit: int = 5) -> list[RecipeInput]:
        ...


class NullRecipeDiscoveryProvider:
    async def discover(self, query: str, limit: int = 5) -> list[RecipeInput]:
        return []

