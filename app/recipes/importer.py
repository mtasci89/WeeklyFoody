from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import BaseModel, Field


class IngredientInput(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None
    category: str | None = None
    note: str | None = None


class RecipeInput(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    cuisine: str | None = None
    category: str = "main"
    meal_type: str = "dinner"
    ingredients: list[IngredientInput] = Field(default_factory=list)
    servings: int = 4
    instructions: str | None = None
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    tags: list[str] = Field(default_factory=list)
    protein_type: str | None = None
    vegetarian: bool = False
    seasonal: list[str] = Field(default_factory=list)
    source: str | None = None
    notes: str | None = None
    status: str = "approved"


class RecipeImporter(Protocol):
    def import_path(self, path: Path) -> list[RecipeInput]:
        ...


class StructuredRecipeImporter:
    def import_path(self, path: Path) -> list[RecipeInput]:
        records: list[dict] = []
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.suffix.lower() in {".yaml", ".yml", ".json"}:
                    records.extend(self.import_path(child))
            return records  # type: ignore[return-value]

        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
        elif path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(raw)
        else:
            raise ValueError(f"Unsupported recipe file: {path}")

        if isinstance(data, dict):
            data = [data]
        return [RecipeInput.model_validate(item) for item in data or []]


class PlainTextRecipeImporter:
    """Small pragmatic parser for Telegram recipe messages."""

    def parse_text(self, text: str) -> RecipeInput:
        cleaned = text.replace("/addrecipe", "").replace("Bu tarifi kaydet:", "").strip()
        lines = [line.strip(" -\t") for line in cleaned.splitlines() if line.strip()]
        if not lines:
            raise ValueError("Recipe text is empty")
        name = lines[0]
        ingredients: list[IngredientInput] = []
        instructions: list[str] = []
        ingredient_units = {"gr", "g", "gram", "kg", "ml", "l", "lt", "adet", "paket", "demet", "yemek kaşığı", "çay kaşığı"}
        for line in lines[1:]:
            lower = line.lower()
            if any(unit in lower.split() for unit in ingredient_units) or any(ch.isdigit() for ch in lower):
                parts = line.split()
                quantity = None
                unit = None
                name_parts = parts
                for idx, part in enumerate(parts):
                    normalized = part.replace(",", ".")
                    try:
                        quantity = float(normalized)
                        unit = parts[idx + 1] if idx + 1 < len(parts) else None
                        name_parts = parts[idx + 2 :]
                        break
                    except ValueError:
                        continue
                ingredient_name = " ".join(name_parts).strip() or line
                ingredients.append(IngredientInput(name=ingredient_name.lower(), quantity=quantity, unit=unit))
            else:
                instructions.append(line)
        return RecipeInput(name=name, ingredients=ingredients, instructions="\n".join(instructions) or None, source="telegram")

