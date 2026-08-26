from __future__ import annotations

from dataclasses import dataclass

from app.shopping.units import format_quantity, to_base


@dataclass
class ShoppingIngredient:
    name: str
    quantity: float | None
    unit: str | None
    category: str
    pantry: bool = False


@dataclass
class ShoppingListItem:
    name: str
    quantity: float | None
    unit: str | None
    category: str
    pantry: bool = False

    def format(self) -> str:
        qty = format_quantity(self.quantity, self.unit)
        return f"{qty} {self.name}".strip()


class ShoppingAggregator:
    def aggregate(self, ingredients: list[ShoppingIngredient]) -> list[ShoppingListItem]:
        buckets: dict[tuple[str, str | None, bool], ShoppingListItem] = {}
        incompatible: list[ShoppingListItem] = []
        for item in ingredients:
            normalized = to_base(item.quantity, item.unit)
            key = (item.name.casefold(), normalized.unit, item.pantry)
            if normalized.quantity is None:
                incompatible.append(ShoppingListItem(item.name, None, normalized.unit, item.category, item.pantry))
                continue
            existing = buckets.get(key)
            if existing is None:
                buckets[key] = ShoppingListItem(item.name, normalized.quantity, normalized.unit, item.category, item.pantry)
            else:
                existing.quantity = (existing.quantity or 0) + normalized.quantity
        return sorted([*buckets.values(), *incompatible], key=lambda item: (item.category, item.name))

