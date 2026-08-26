from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import MealPlan, MealPlanItem, PantryItem
from app.shopping.aggregator import ShoppingAggregator, ShoppingIngredient, ShoppingListItem

CATEGORY_ORDER = [
    "Et / Tavuk / Balık",
    "Sebze & Meyve",
    "Süt Ürünleri",
    "Bakliyat",
    "Kuru Gıda / Baharat",
    "Diğer",
    "Evde kontrol et",
]


class ShoppingListService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings

    def generate(self, plan: MealPlan) -> list[ShoppingListItem]:
        pantry = {p.ingredient_name.casefold() for p in self.db.scalars(select(PantryItem))}
        raw: list[ShoppingIngredient] = []
        for item in plan.items:
            raw.extend(self._ingredients_for_item(item, pantry))
        aggregated = ShoppingAggregator().aggregate(raw)
        if self.settings.pantry_mode == "exclude":
            return [item for item in aggregated if not item.pantry]
        for item in aggregated:
            if item.pantry:
                item.category = "Evde kontrol et"
        return aggregated

    def _ingredients_for_item(self, item: MealPlanItem, pantry: set[str]) -> list[ShoppingIngredient]:
        recipe = item.recipe
        scale = (item.servings or self.settings.default_servings) / recipe.servings
        ingredients: list[ShoppingIngredient] = []
        for ingredient in recipe.ingredients:
            name = ingredient.ingredient.name
            ingredients.append(
                ShoppingIngredient(
                    name=name,
                    quantity=ingredient.quantity * scale if ingredient.quantity is not None else None,
                    unit=ingredient.unit,
                    category=ingredient.ingredient.category or "Diğer",
                    pantry=name.casefold() in pantry,
                )
            )
        return ingredients

    def format(self, items: list[ShoppingListItem]) -> str:
        grouped: dict[str, list[ShoppingListItem]] = defaultdict(list)
        for item in items:
            grouped[item.category].append(item)
        lines = ["🛒 Alışveriş Listesi"]
        for category in CATEGORY_ORDER:
            category_items = grouped.get(category)
            if not category_items:
                continue
            lines.append(f"\n*{self._category_title(category)}*")
            for item in category_items:
                lines.append(f"- {item.format()}")
        for category, category_items in grouped.items():
            if category in CATEGORY_ORDER:
                continue
            lines.append(f"\n*{category}*")
            for item in category_items:
                lines.append(f"- {item.format()}")
        return "\n".join(lines)

    def _category_title(self, category: str) -> str:
        icons = {
            "Et / Tavuk / Balık": "🥩 Et / Tavuk / Balık",
            "Sebze & Meyve": "🥬 Sebze & Meyve",
            "Süt Ürünleri": "🥛 Süt Ürünleri",
            "Bakliyat": "🫘 Bakliyat",
            "Kuru Gıda / Baharat": "🧂 Kuru Gıda / Baharat",
            "Evde kontrol et": "🏠 Evde kontrol et",
        }
        return icons.get(category, category)

