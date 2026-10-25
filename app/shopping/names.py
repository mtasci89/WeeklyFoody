"""Shopping identities only: recipe names and stored ingredient records stay intact."""
from __future__ import annotations

import re
import unicodedata

from app.shopping.units import normalize_unit


def name_key(name: str) -> str:
    text = unicodedata.normalize("NFC", name).casefold().replace("i\u0307", "i")
    return " ".join(text.translate(str.maketrans("çğıöşü", "cgiosu")).split())


ALIASES = {
    "dana kusbasi": "dana kuşbaşı", "kusbasi dana eti": "dana kuşbaşı",
    "dana kusbasi eti": "dana kuşbaşı", "dana eti kusbasi": "dana kuşbaşı",
    "kuzu kusbasi": "kuzu kuşbaşı", "kusbasi kuzu eti": "kuzu kuşbaşı",
    "kuzu kusbasi eti": "kuzu kuşbaşı", "kuzu eti kusbasi": "kuzu kuşbaşı",
    "kusbasi et": "kuşbaşı et", "kusbasi eti": "kuşbaşı et",
    "tavuk gogsu": "tavuk göğsü", "kusbasi tavuk gogsu": "tavuk göğsü",
    "tavuk gogsu kusbasi": "tavuk göğsü", "tavuk gogus eti": "tavuk göğsü",
    "tavuk gogus": "tavuk göğsü", "tavuk gogsu eti": "tavuk göğsü",
    "sarimsak": "sarımsak", "sogan": "soğan", "domates": "domates",
    "olgun domates": "domates", "dereotu": "dereotu",
    "taze feslegen": "taze fesleğen", "kuru feslegen": "kuru fesleğen",
    "feslegen": "fesleğen", "limon": "limon", "limon suyu": "limon suyu",
    "limonun suyu": "limon suyu", "taze sikilmis limon suyu": "limon suyu",
    "zeytin yagi": "zeytinyağı", "zeytinyagi": "zeytinyağı",
}
PREPARATION = re.compile(
    r"\b(?:(?:ince|iri|küçük|kucuk|küp küp|kup kup|küp|kup|jülyen|julyen)\s+)?"
    r"(?:doğranmış|dogranmis|kıyılmış|kiyilmis|rendelenmiş|rendelenmis|ezilmiş|ezilmis|soyulmuş|soyulmus)\b"
)
EMBEDDED_AMOUNT = re.compile(
    r"^(yarım|çeyrek|\d+(?:[.,]\d+)?(?:/\d+)?)\s+"
    r"(yemek kaşığı|tatlı kaşığı|çay kaşığı|su bardağı|demet|adet|diş|baş|g|gr|kg|ml|l)\s+(.+)$"
)


def normalize_ingredient(name: str, quantity: float | None, unit: str | None) -> tuple[str, float | None, str | None]:
    """Remove preparation wording; preserve cuts, species and fresh/dry products."""
    name = " ".join(unicodedata.normalize("NFC", name).casefold().replace("i\u0307", "i").split()).strip()
    unit = normalize_unit(unit)
    if quantity is None and unit is None:
        match = EMBEDDED_AMOUNT.fullmatch(name)
        if match:
            amount, unit, name = match.groups()
            if amount in {"yarım", "çeyrek"}:
                quantity = {"yarım": 0.5, "çeyrek": 0.25}[amount]
            elif "/" in amount:
                numerator, denominator = amount.split("/")
                if float(denominator) == 0:
                    return name, None, unit
                quantity = float(numerator.replace(",", ".")) / float(denominator)
            else:
                quantity = float(amount.replace(",", "."))
    if quantity is None and name.startswith("birkaç yaprak "):
        name, unit = name.removeprefix("birkaç yaprak "), "birkaç yaprak"
    # Clove/head is explicit in these names; plain "adet sarımsak" stays ambiguous.
    if name_key(name) in {"dis sarimsak", "bas sarimsak"}:
        if unit in {None, "adet"}:
            unit = "diş" if name_key(name).startswith("dis ") else "baş"
            name = "sarımsak"
    clean = " ".join(PREPARATION.sub(" ", name.replace("(", " ").replace(")", " ").replace(",", " ")).split())
    key = name_key(clean)
    canonical = ALIASES.get(key)
    if canonical is None:
        canonical = clean
    if canonical == "limon suyu" and unit == "adet":
        canonical = "limon"
    if canonical == "fesleğen" and unit in {"demet", "yaprak"}:
        canonical = "taze fesleğen"
    return canonical, quantity, normalize_unit(unit)


def canonical_name(name: str) -> str:
    return normalize_ingredient(name, None, None)[0]
