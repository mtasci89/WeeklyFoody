from __future__ import annotations

from dataclasses import dataclass


UNIT_ALIASES = {
    "gr": "g",
    "gram": "g",
    "kilogram": "kg",
    "mililitre": "ml",
    "tane": "adet",
    "dis": "diş",
    "bas": "baş",
    "yaprak": "yaprak",
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
    "tatlı kaşığı": "tatlı kaşığı",
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
    text = " ".join(unit.strip().casefold().replace("i\u0307", "i").split())
    return UNIT_ALIASES.get(text, text)


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


COUNT_UNITS = {"adet", "demet", "paket", "diş", "dilim", "kutu", "kavanoz", "baş", "tutam"}
SPOON_UNITS = {"yemek kaşığı", "çay kaşığı", "tatlı kaşığı", "su bardağı", "çay bardağı", "kase"}


def _ceil_to(value: float, step: float) -> float:
    import math

    return math.ceil(round(value / step, 6)) * step


def shopping_quantity(quantity: float | None, unit: str | None) -> float | None:
    """Alisveriste alinabilir bir miktar: porsiyon olcekleme "333,33 g tavuk"
    ya da "0,67 adet sarimsak" uretiyordu. Her zaman yukari yuvarlar: eksik
    almak fazla almaktan kotudur."""
    if quantity is None or quantity <= 0:
        return quantity
    if unit in ("g", "ml"):
        step = 5 if quantity < 50 else 10 if quantity < 250 else 50
        return _ceil_to(quantity, step)
    if unit in COUNT_UNITS:
        return _ceil_to(quantity, 1)
    if unit in SPOON_UNITS:
        return _ceil_to(quantity, 0.5)
    return round(quantity, 1)


def format_shopping_quantity(quantity: float | None, unit: str | None) -> str:
    """Turkce ondalik virgulle: "1,5 kg", "350 g", "1 adet"."""
    if quantity is None:
        return ""
    value, display_unit = display_quantity(shopping_quantity(quantity, unit), unit)
    formatted = f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{formatted} {display_unit}".strip() if display_unit else formatted
