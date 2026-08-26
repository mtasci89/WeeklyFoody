from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Ingredient, Recipe, RecipeIngredient, RecipeStatus
from app.recipes.discovery import build_recipe_discovery_provider
from app.recipes.importer import ExcelMenuRecipeImporter, PlainTextRecipeImporter, RecipeInput, StructuredRecipeImporter


def normalize_name(name: str) -> str:
    return " ".join(name.casefold().strip().split())


class RecipeService:
    def __init__(self, db: Session):
        self.db = db

    def upsert_recipe(self, recipe_input: RecipeInput) -> Recipe:
        recipe = self.find_recipe(recipe_input.name, include_inactive=True)
        if recipe and recipe.status == RecipeStatus.APPROVED and recipe_input.status == RecipeStatus.CANDIDATE.value:
            return recipe
        if recipe is None:
            recipe = Recipe(name=recipe_input.name)
            self.db.add(recipe)
        recipe.aliases = recipe_input.aliases
        recipe.cuisine = recipe_input.cuisine
        recipe.category = recipe_input.category
        recipe.meal_type = recipe_input.meal_type
        recipe.servings = recipe_input.servings
        recipe.instructions = recipe_input.instructions
        recipe.prep_minutes = recipe_input.prep_minutes
        recipe.cook_minutes = recipe_input.cook_minutes
        recipe.tags = recipe_input.tags
        recipe.protein_type = recipe_input.protein_type
        recipe.vegetarian = recipe_input.vegetarian
        recipe.seasonal = recipe_input.seasonal
        recipe.source = recipe_input.source
        recipe.notes = recipe_input.notes
        recipe.status = RecipeStatus(recipe_input.status)
        recipe.ingredients.clear()
        self.db.flush()
        for index, item in enumerate(recipe_input.ingredients):
            ingredient = self.get_or_create_ingredient(item.name, item.category)
            recipe.ingredients.append(
                RecipeIngredient(
                    ingredient=ingredient,
                    quantity=item.quantity,
                    unit=item.unit,
                    position=index,
                    note=item.note,
                )
            )
        self.db.commit()
        self.db.refresh(recipe)
        return recipe

    def import_recipes(self, path: Path) -> int:
        importer = StructuredRecipeImporter()
        count = 0
        for recipe in importer.import_path(path):
            self.upsert_recipe(recipe)
            count += 1
        return count

    def import_menu_excel(self, path: Path) -> int:
        importer = ExcelMenuRecipeImporter()
        count = 0
        for recipe in importer.import_path(path):
            self.upsert_recipe(recipe)
            count += 1
        return count

    def add_recipe_from_text(self, text: str) -> Recipe:
        return self.upsert_recipe(PlainTextRecipeImporter().parse_text(text))

    def get_or_create_ingredient(self, name: str, category: str | None = None) -> Ingredient:
        normalized = normalize_name(name)
        ingredient = self.db.scalar(select(Ingredient).where(Ingredient.name == normalized))
        if ingredient is None:
            ingredient = Ingredient(name=normalized, category=category or categorize_ingredient(normalized))
            self.db.add(ingredient)
            self.db.flush()
        elif category and not ingredient.category:
            ingredient.category = category
        return ingredient

    def find_recipe(self, name: str, include_inactive: bool = False) -> Recipe | None:
        needle = normalize_name(name)
        recipes = self.db.scalars(select(Recipe)).all()
        for recipe in recipes:
            names = [recipe.name, *(recipe.aliases or [])]
            if any(normalize_name(candidate) == needle for candidate in names):
                if include_inactive or recipe.status != RecipeStatus.INACTIVE:
                    return recipe
        return None

    def list_recipes(self, include_candidates: bool = False) -> list[Recipe]:
        statuses = [RecipeStatus.APPROVED]
        if include_candidates:
            statuses.append(RecipeStatus.CANDIDATE)
        return list(self.db.scalars(select(Recipe).where(Recipe.status.in_(statuses)).order_by(Recipe.name)))

    def list_candidates(self) -> list[Recipe]:
        return list(self.db.scalars(select(Recipe).where(Recipe.status == RecipeStatus.CANDIDATE).order_by(Recipe.created_at.desc())))

    async def discover_recipes(self, query: str, settings: Settings, limit: int = 3) -> list[Recipe]:
        provider = build_recipe_discovery_provider(settings)
        discovered = await provider.discover(query, limit=limit)
        recipes: list[Recipe] = []
        for recipe_input in discovered:
            recipes.append(self.upsert_recipe(recipe_input))
        return recipes

    def disable_recipe(self, name: str) -> bool:
        recipe = self.find_recipe(name)
        if not recipe:
            return False
        recipe.status = RecipeStatus.INACTIVE
        self.db.commit()
        return True

    def approve_candidate(self, name: str) -> bool:
        recipe = self.find_recipe(name, include_inactive=True)
        if not recipe or recipe.status != RecipeStatus.CANDIDATE:
            return False
        recipe.status = RecipeStatus.APPROVED
        self.db.commit()
        return True


def categorize_ingredient(name: str) -> str:
    lower = normalize_name(name)
    meat = ("et", "kıyma", "tavuk", "balık", "somon", "hamsi", "kuşbaşı")
    veg = ("domates", "soğan", "biber", "patates", "havuç", "fasulye", "kabak", "maydanoz", "limon")
    dairy = ("yoğurt", "süt", "peynir", "kaşar", "tereyağı")
    legumes = ("mercimek", "nohut", "kuru fasulye", "bulgur")
    dry = ("pirinç", "makarna", "un", "salça", "tuz", "karabiber", "zeytinyağı", "baharat")
    if any(token in lower for token in meat):
        return "Et / Tavuk / Balık"
    if any(token in lower for token in dairy):
        return "Süt Ürünleri"
    if any(token in lower for token in legumes):
        return "Bakliyat"
    if any(token in lower for token in veg):
        return "Sebze & Meyve"
    if any(token in lower for token in dry):
        return "Kuru Gıda / Baharat"
    return "Diğer"
