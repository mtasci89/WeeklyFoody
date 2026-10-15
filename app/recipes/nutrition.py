"""User-supplied nutrition per one serving. Never infer missing values."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class NutritionInput(BaseModel):
    calories_kcal: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    protein_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: str = Field(min_length=1, max_length=500)
    estimated: bool = True

    @model_validator(mode='after')
    def require_values_and_source(self):
        self.source = self.source.strip()
        if not self.source or (self.calories_kcal is None and self.protein_g is None):
            raise ValueError('Kaynak ve en az bir besin değeri gerekli.')
        return self


def nutrition_text(recipe) -> str:
    nutrition = recipe.nutrition
    if nutrition is None:
        return 'kalori/protein bilgisi yok'
    kcal = f'{nutrition.calories_kcal:g} kcal' if nutrition.calories_kcal is not None else 'kalori bilinmiyor'
    protein = f'{nutrition.protein_g:g} g protein' if nutrition.protein_g is not None else 'protein bilinmiyor'
    return f'{kcal}, {protein} / kişi' + (' (tahmini)' if nutrition.estimated else ' (kayıtlı değer)')


def save_nutrition(db, recipe, values: NutritionInput | None):
    from app.db.models import RecipeNutrition
    if values is None:
        recipe.nutrition = None
    else:
        if recipe.nutrition is None:
            recipe.nutrition = RecipeNutrition()
        for key, value in values.model_dump().items():
            setattr(recipe.nutrition, key, value)
    db.flush()
