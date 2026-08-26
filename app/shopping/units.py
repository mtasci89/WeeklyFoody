from __future__ import annotations

from dataclasses import dataclass


UNIT_ALIASES = {
    "gr": "g",
    "gram": "g",
    "g": "g",
    "kg": "kg",
    "ml": "ml",
    "l": "l",
    "lt": "l",
    "litre": "l",
    "adet": "adet",
    "paket": "paket",
    "demet": "demet",
    "yemek kaşığı": "yemek kaşığı",
    "çay kaşığı": "çay kaşığı",
    "tbsp": "yemek kaşığı",
    "tsp": "çay kaşığı",
}


@dataclass(frozen=True)
class NormalizedQuantity:
    quantity: float | None
    unit: str | None


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    return UNIT_ALIASES.get(unit.strip().casefold(), unit.strip().casefold())


def to_base(quantity: float | None, unit: str | None) -> NormalizedQuantity:
    normalized = normalize_unit(unit)
    if quantity is None:
        return NormalizedQuantity(None, normalized)
    if normalized == "kg":
        return NormalizedQuantity(quantity * 1000, "g")
    if normalized == "l":
        return NormalizedQuantity(quantity * 1000, "ml")
    return NormalizedQuantity(quantity, normalized)


def display_quantity(quantity: float | None, unit: str | None) -> tuple[float | None, str | None]:
    if quantity is None:
        return None, unit
    if unit == "g" and quantity >= 1000:
        return quantity / 1000, "kg"
    if unit == "ml" and quantity >= 1000:
        return quantity / 1000, "L"
    return quantity, unit


def format_quantity(quantity: float | None, unit: str | None) -> str:
    if quantity is None:
        return ""
    value, display_unit = display_quantity(quantity, unit)
    if value is None:
        return ""
    formatted = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{formatted} {display_unit}".strip() if display_unit else formatted

