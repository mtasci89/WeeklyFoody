from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.db.models import MealPlan, WeeklyPlanningSession
from app.config import course_role
from app.planner.dates import TR_DAY_NAMES

MONTHS_TR = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}


def format_date_range(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.day} - {end.day} {MONTHS_TR[end.month]}"
    return f"{start.day} {MONTHS_TR[start.month]} - {end.day} {MONTHS_TR[end.month]}"


def format_meal_plan(session: WeeklyPlanningSession, final: bool = False) -> str:
    if not session.meal_plan:
        return "Aktif menü bulunamadı."
    title = "KESİN MENÜ" if final else "Yemek Planı Taslağı"
    lines = [f"*🍽️ {format_date_range(session.week_start, session.week_end)} {title}*"]
    lines.append("")
    by_date = defaultdict(list)
    for item in sorted(session.meal_plan.items, key=lambda i: (i.date, i.meal_slot)):
        by_date[item.date].append(item)
    for day, items in by_date.items():
        lines.append(f"*{TR_DAY_NAMES[day.weekday()]}*")
        for item in items:
            servings = f" ({item.servings} kişi)" if item.servings else ""
            label = course_label(item.meal_slot)
            lines.append(f"• {label}: {item.recipe.name}{servings}")
        lines.append("")
    return "\n".join(lines).strip()


def course_label(meal_slot: str) -> str:
    role = course_role(meal_slot)
    labels = {
        "main": "Ana yemek",
        "meze": "Meze/salata",
        "salad": "Meze/salata",
        "side": "Yan",
    }
    return labels.get(role, role.replace("_", " ").title())


def format_recipe_detail(recipe) -> str:
    lines = [f"*{recipe.name}*", f"Porsiyon: {recipe.servings}", ""]
    if recipe.ingredients:
        lines.append("*Malzemeler*")
        for ingredient in recipe.ingredients:
            qty = ""
            if ingredient.quantity is not None:
                qty = f"{ingredient.quantity:g} {ingredient.unit or ''}".strip()
            lines.append(f"- {qty} {ingredient.ingredient.name}".strip())
    if recipe.instructions:
        lines.extend(["", "*Hazırlık*", recipe.instructions])
    return "\n".join(lines)


def format_candidate_recipes(recipes) -> str:
    if not recipes:
        return "Aday tarif yok."
    lines = ["*Aday Tarifler*"]
    for recipe in recipes:
        effort = (recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)
        effort_text = f", {effort} dk" if effort else ""
        ingredient_count = len(recipe.ingredients or [])
        lines.append(f"- {recipe.name} ({recipe.category}, {ingredient_count} malzeme{effort_text})")
    lines.append("")
    lines.append("Kalıcı yapmak için: `/approverecipe Tarif Adı`")
    return "\n".join(lines)
