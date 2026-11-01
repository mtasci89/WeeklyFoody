"""Course roles derived from the dish, including incorrectly labelled old recipes.

Model-supplied category/protein labels are not evidence that a garnish is a main.
This does not restrict ingredients: mushrooms can accompany a genuine main dish.
"""
from __future__ import annotations

import re


def _normal(text: str) -> str:
    return text.casefold().replace("i\u0307", "i").translate(str.maketrans("çğıöşü", "cgiosu"))


def _contains(text: str, pattern: str) -> bool:
    return bool(re.search(r"\b(?:" + pattern + r")\w*", text))


def recipe_category(recipe) -> str:
    """Accept both RecipeInput and ORM recipes, without changing stored records."""
    category = (getattr(recipe, "category", None) or "main").casefold()
    name = _normal(recipe.name)
    # Dish form wins over a model's category, even for chicken salad/stock pilaf.
    if _contains(name, "corba|soup"):
        return "soup"
    if _contains(name, "salata|salad|piyaz|tabule|tabbouleh"):
        return "salad"
    if _contains(name, "meze|haydari|humus|hummus|cacik|ezme|muhammara|saksuka|tarator|guacamole") or "mercimek kofte" in name:
        return "meze"
    if _contains(name, "pilav|risotto|rizotto|makarna|pasta|eriste|noodle|sehriye"):
        return "side"
    if category != "main":
        return category
    if "meze" in {_normal(tag) for tag in getattr(recipe, "tags", None) or []}:
        return "meze"
    ingredients = []
    for item in getattr(recipe, "ingredients", None) or []:
        ingredient = getattr(item, "ingredient", item)
        ingredients.append(_normal(getattr(ingredient, "name", "")))
    # Stock/bouillon/sauce do not turn a vegetable dish into a meat main.
    def without_stock(text: str) -> str:
        return re.sub(
            r"\b(?:tavuk|et|kemik|dana|balik|chicken|beef|fish)\s+(?:suy\w*|bulyon\w*|stock|broth)\b",
            "", text,
        )
    protein_text = " ".join(without_stock(text) for text in [name, *ingredients])
    substantial = _contains(
        protein_text,
        "tavuk|chicken|hindi|turkey|dana|kuzu|kiyma|bonfile|antrikot|pirzola|kusbasi|"
        "etli|eti|beef|lamb|balik|somon|levrek|cipura|palamut|uskumru|hamsi|ton|"
        "karides|salmon|fish|tofu|tempeh|nohut|mercimek|kuru fasulye|barbunya|yumurta",
    )
    if not substantial:
        if any(_contains(text, "mantar|mushroom") for text in [name, *ingredients]):
            return "side"
        vegetables = _contains(name, "biber|patlican|brokoli|karnabahar|havuc|kabak|patates|kinoa|quinoa|bulgur")
        garnish = _contains(name, "koz|kozlenmis|sote|pure|cubuk|haslama|buharda|firinlanmis|kruton|graten|kizartma")
        if vegetables and garnish:
            return "side"
    return category


def matches_course_role(recipe, role: str) -> bool:
    category = recipe_category(recipe)
    role = role.casefold()
    if role in {"meze", "salad"}:
        return category in {"meze", "salad"}
    if role == "side":
        return category in {"side", "soup", "grain", "pasta", "pilaf"}
    return category == role
