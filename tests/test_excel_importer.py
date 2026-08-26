from __future__ import annotations

from openpyxl import Workbook

from app.recipes.service import RecipeService


def test_import_menu_excel_extracts_clean_recipe_names(db, tmp_path):
    path = tmp_path / "menu.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["", "Pazartesi", "Salı"])
    sheet.append(["Akşam", "Mercimek Çorbası\nEt Sote\nSalata\nYoğurt", "150gr. Izgara tavuk göğüs\n1 dilim wasa fibre"])
    workbook.save(path)

    count = RecipeService(db).import_menu_excel(path)
    recipes = RecipeService(db).list_recipes()
    names = {recipe.name for recipe in recipes}

    assert count == 3
    assert "Mercimek Çorbası" in names
    assert "Et Sote" in names
    assert "Izgara tavuk göğüs" in names
    assert "Yoğurt" not in names
    assert "1 dilim wasa fibre" not in names

