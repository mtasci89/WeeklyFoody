"""Parse amount/unit/name lines produced by recipe tools and web research."""
from app.recipes.importer import IngredientInput

UNITS = {
    "gr", "g", "gram", "kg", "ml", "l", "lt", "litre", "adet", "paket", "demet",
    "diş", "dis", "dal", "tutam", "su bardağı", "çay bardağı", "yemek kaşığı",
    "çay kaşığı", "tatlı kaşığı",
}


def parse_ingredient(line: str) -> IngredientInput:
    """"600 gr tavuk" -> (600, "gr", "tavuk").

    Modele tek tek malzeme satiri yazdirdigimiz icin burada talimat metni
    beklemiyoruz; eski duz metin ayristiricinin "rakam gecen her satir
    malzemedir" varsayimi burada yok.
    """
    tokens = line.strip().split()
    if not tokens:
        return IngredientInput(name=line.strip() or "bilinmeyen")
    try:
        quantity = float(tokens[0].replace(",", "."))
    except ValueError:
        return IngredientInput(name=" ".join(tokens).casefold())
    rest = tokens[1:]
    unit = None
    # Iki kelimelik birimler ("yemek kaşığı") tek kelimelilerden once denenir.
    if len(rest) >= 2 and " ".join(rest[:2]).casefold() in UNITS:
        unit, rest = " ".join(rest[:2]).casefold(), rest[2:]
    elif rest and rest[0].casefold() in UNITS:
        unit, rest = rest[0].casefold(), rest[1:]
    name = " ".join(rest).casefold().strip()
    return IngredientInput(name=name or line.strip().casefold(), quantity=quantity, unit=unit)


