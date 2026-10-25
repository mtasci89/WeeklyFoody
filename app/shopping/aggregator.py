from __future__ import annotations

from dataclasses import dataclass, field

from app.shopping.names import name_key, normalize_ingredient
from app.shopping.units import NormalizedQuantity, format_shopping_quantity, to_base


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
    amounts: list[NormalizedQuantity] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def format(self) -> str:
        if self.amounts:
            # Don't invent a head-to-clove or grams-to-pieces conversion.
            qty = " + ".join(format_shopping_quantity(p.quantity, p.unit) for p in self.amounts)
        else:
            qty = format_shopping_quantity(self.quantity, self.unit)
        qty = " + ".join(part for part in [qty, *self.notes] if part)
        return f"{qty} {self.name}".strip()


class ShoppingAggregator:
    def aggregate(self, ingredients: list[ShoppingIngredient]) -> list[ShoppingListItem]:
        rows = []
        for item in ingredients:
            name, quantity, unit = normalize_ingredient(item.name, item.quantity, item.unit)
            rows.append((item, name, to_base(quantity, unit)))
        # Unqualified kuşbaşı follows the only explicitly identified red-meat type.
        # When both beef and lamb are present the unqualified item stays separate.
        species = {name for _, name, _ in rows if name in {"dana kuşbaşı", "kuzu kuşbaşı"}}
        buckets: dict[tuple[str, bool], ShoppingListItem] = {}
        totals: dict[tuple[str, bool], dict[str | None, float]] = {}
        for item, name, amount in rows:
            if name == "kuşbaşı et" and len(species) == 1:
                name = next(iter(species))
            key = (name_key(name), item.pantry)
            if key not in buckets:
                buckets[key] = ShoppingListItem(name, None, None, item.category, item.pantry)
                totals[key] = {}
            if amount.quantity is None and amount.unit and amount.unit.startswith("birkaç"):
                if amount.unit not in buckets[key].notes:
                    buckets[key].notes.append(amount.unit)
            if amount.quantity is not None:
                totals[key][amount.unit] = totals[key].get(amount.unit, 0) + amount.quantity
        for key, item in buckets.items():
            parts = [NormalizedQuantity(quantity, unit) for unit, quantity in totals[key].items()]
            parts.sort(key=lambda p: p.unit or "")
            if len(parts) == 1:
                item.quantity, item.unit = parts[0].quantity, parts[0].unit
            elif parts:
                item.amounts = parts
        return sorted(buckets.values(), key=lambda item: (item.category, item.name))
