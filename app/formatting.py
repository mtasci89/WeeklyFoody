from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.db.models import MealPlan, WeeklyPlanningSession
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
            lines.append(f"• {item.recipe.name}{servings}")
        lines.append("")
    return "\n".join(lines).strip()


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

