"""Günün tabağı: ana yemek ile yan yemeğin / çorbanın birbirine uyumu.

Kullanıcı: "Günlük yemek ve yan yemeğin birbiriyle uyumuna da dikkat etsin,
alakasız olmasınlar." Bu bir YASAK değildir (kullanıcı katı kuralları "aptalca"
buldu); bulunan uyumsuzluklar modele düşünmesi için not olarak verilir, yedek
planlayıcı ve yeni yemek seçimi ise uyumlu olanı öne alır.
"""
from __future__ import annotations

from dataclasses import dataclass

PROTEIN_WORDS = [
    ("balık", ("balık", "somon", "levrek", "çipura", "hamsi", "uskumru", "palamut", "ton ", "karides", "fish")),
    ("tavuk", ("tavuk", "hindi", "chicken")),
    ("kırmızı et", ("dana", "kuzu", "kıyma", "köfte", "bonfile", "biftek", "et sote", "etli", "beef", "lamb", "bulgogi")),
    ("baklagil", ("nohut", "fasulye", "mercimek", "barbunya", "bakla", "legume")),
    ("yumurta", ("yumurta", "menemen", "shakshuka", "egg")),
]
PROTEIN_TYPES = {"chicken": "tavuk", "fish": "balık", "beef": "kırmızı et", "lamb": "kırmızı et",
                 "legumes": "baklagil", "egg": "yumurta", "eggs": "yumurta"}

# Tabakta ikisi birden olunca "hep hamur/pilav" olan şeyler.
STARCH_WORDS = (
    "pilav", "makarna", "erişte", "patates", "bulgur", "kuskus", "mantı", "noodle", "lazanya", "risotto",
    "börek", "pide", "lahmacun", "pizza", "spagetti", "penne", "şehriye", "kinoa", "pirinç", "gnocchi",
    "orzo", "dürüm", "wrap", "burrito", "taco", "tortilla", "ramen", "pasta", "fettuccine", "tagliatelle",
)

# Ad ya da kayıtlı mutfak alanından mutfak ailesi. Bilinmiyorsa "" (hiçbir şey denmez).
CUISINE_WORDS = [
    ("Asya", ("kore", "japon", "çin", "tay ", "tayland", "vietnam", "hint", "asya", "asian", "korean", "japanese",
              "chinese", "thai", "indian", "teriyaki", "köri", "curry", "bulgogi", "kimchi", "gochujang", "wok",
              "ramen", "sushi", "tandoori", "masala", "tikka", "satay", "miso", "katsu", "noodle", "soya soslu",
              "pad thai", "dal ", "biryani")),
    ("Latin", ("meksika", "mexican", "latin", "taco", "burrito", "fajita", "quesadilla", "enchilada", "chili",
               "peru", "brezilya", "arjantin", "chimichurri", "guacamole", "nachos", "tortilla")),
    ("İtalyan", ("italyan", "italian", "risotto", "lazanya", "pesto", "carbonara", "bolonez", "gnocchi",
                 "parmigiana", "piccata", "bruschetta", "fettuccine", "tagliatelle", "penne", "spagetti")),
    ("Türk", ("zeytinyağlı", "cacık", "piyaz", "sarma", "dolma", "bulgur", "ezogelin", "tarhana", "yayla",
              "haydari", "kısır", "mantı", "imam bayıldı", "hünkar", "karnıyarık", "türlü", "güveç", "kuru fasulye",
              "etli nohut", "mercimek çorbası", "işkembe", "kavurma", "türk", "turkish", "anadolu", "osmanlı",
              "şehriyeli", "arpa şehriye", "bamya", "taze fasulye")),
]
CUISINE_ALIASES = {
    "korean": "Asya", "japanese": "Asya", "chinese": "Asya", "thai": "Asya", "indian": "Asya", "asian": "Asya",
    "vietnamese": "Asya", "mexican": "Latin", "latin": "Latin", "italian": "İtalyan", "turkish": "Türk",
}


@dataclass(frozen=True)
class Dish:
    name: str
    category: str = ""
    cuisine: str = ""
    protein_type: str = ""
    ingredients: tuple[str, ...] = ()


def dish_of(obj) -> Dish:
    """Recipe nesnesi, planlayıcının sözlüğü ya da yalnızca ad -> Dish."""
    if isinstance(obj, Dish):
        return obj
    if isinstance(obj, str):
        return Dish(obj)
    if isinstance(obj, dict):
        return Dish(
            str(obj.get("name") or obj.get("ad") or ""), str(obj.get("category") or ""),
            str(obj.get("cuisine") or obj.get("mutfak") or ""), str(obj.get("protein_type") or obj.get("protein") or ""),
            tuple(str(x) for x in obj.get("malzemeler") or ()),
        )
    names = ()
    try:
        names = tuple(i.ingredient.name for i in getattr(obj, "ingredients", None) or ())
    except AttributeError:
        names = ()
    return Dish(
        getattr(obj, "name", "") or "", getattr(obj, "category", "") or "", getattr(obj, "cuisine", "") or "",
        getattr(obj, "protein_type", "") or "", names,
    )


def _text(dish: Dish, with_ingredients: bool = False) -> str:
    parts = [dish.name, *(dish.ingredients if with_ingredients else ())]
    return " " + " ".join(parts).casefold() + " "


def protein_group(obj) -> str:
    dish = dish_of(obj)
    kind = PROTEIN_TYPES.get(dish.protein_type.casefold())
    if kind:
        return kind
    text = _text(dish, with_ingredients=True)
    return next((label for label, words in PROTEIN_WORDS if any(w in text for w in words)), "")


def cuisine_family(obj) -> str:
    dish = dish_of(obj)
    alias = CUISINE_ALIASES.get(dish.cuisine.casefold().strip())
    if alias:
        return alias
    text = _text(dish) + " " + dish.cuisine.casefold() + " "
    return next((family for family, words in CUISINE_WORDS if any(w in text for w in words)), "")


def is_starchy(obj) -> bool:
    dish = dish_of(obj)
    text = _text(dish)
    return dish.category.casefold() in {"pasta", "pilaf", "grain"} or any(w in text for w in STARCH_WORDS)


def pairing_issues(main, side) -> list[str]:
    """Ana yemek + yan yemek/çorba arasındaki olası uyumsuzluklar (kısa, Türkçe)."""
    from app.agent.fresh import key_words

    main, side = dish_of(main), dish_of(side)
    if not main.name or not side.name:
        return []
    issues: list[str] = []
    if is_starchy(main) and is_starchy(side):
        issues.append("ikisi de nişastalı (hamur/pilav/patates)")
    shared = key_words(main.name) & key_words(side.name)
    if shared:
        issues.append(f"aynı ana malzeme ({', '.join(sorted(shared))})")
    else:
        main_protein, side_protein = protein_group(main), protein_group(side)
        if main_protein and main_protein == side_protein:
            issues.append(f"ikisi de {main_protein}")
    main_family, side_family = cuisine_family(main), cuisine_family(side)
    if main_family and side_family and main_family != side_family:
        issues.append(f"mutfaklar uyuşmuyor ({main_family} ana yemek, {side_family} yan)")
    return issues


def pairing_penalty(main, side) -> int:
    return len(pairing_issues(main, side))
