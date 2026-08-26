from __future__ import annotations

import json
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class PlannedMeal(BaseModel):
    date: str
    meal_slot: str
    recipe_id: str
    servings: int | None = None
    reason: str | None = None


class WeeklyPlanOutput(BaseModel):
    meals: list[PlannedMeal]
    notes: str | None = None


class Intent(str, Enum):
    MODIFY_PLAN = "MODIFY_PLAN"
    APPROVE_PLAN = "APPROVE_PLAN"
    REGENERATE_PLAN = "REGENERATE_PLAN"
    ADD_RECIPE = "ADD_RECIPE"
    DELETE_RECIPE = "DELETE_RECIPE"
    SHOW_RECIPE = "SHOW_RECIPE"
    ADD_PREFERENCE = "ADD_PREFERENCE"
    DELETE_PREFERENCE = "DELETE_PREFERENCE"
    SHOW_PREFERENCES = "SHOW_PREFERENCES"
    ADD_PANTRY_ITEM = "ADD_PANTRY_ITEM"
    REMOVE_PANTRY_ITEM = "REMOVE_PANTRY_ITEM"
    SHOW_MENU = "SHOW_MENU"
    SHOW_SHOPPING_LIST = "SHOW_SHOPPING_LIST"
    DISCOVER_RECIPE = "DISCOVER_RECIPE"
    SHOW_RECIPE_CANDIDATES = "SHOW_RECIPE_CANDIDATES"
    APPROVE_RECIPE_CANDIDATE = "APPROVE_RECIPE_CANDIDATE"
    GENERAL_QUESTION = "GENERAL_QUESTION"
    UNKNOWN = "UNKNOWN"


class PreferencePayload(BaseModel):
    type: str = "hard"
    rule: str


class IntentOutput(BaseModel):
    intent: Intent
    confidence: float = 0.5
    recipe_name: str | None = None
    recipe_text: str | None = None
    preference: PreferencePayload | None = None
    pantry_item: str | None = None
    discovery_query: str | None = None
    clarification_question: str | None = None
    raw_request: str | None = None


class RevisionOperation(BaseModel):
    date: str | None = None
    day_name: str | None = None
    meal_slot: str | None = None
    recipe_name: str | None = None
    exclude_recipe_name: str | None = None
    servings: int | None = None
    instruction: str | None = None


class RevisionOutput(BaseModel):
    operations: list[RevisionOperation] = Field(default_factory=list)
    permanent_preference: PreferencePayload | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None


class LLMProvider(Protocol):
    async def generate_plan(self, context: dict[str, Any]) -> WeeklyPlanOutput:
        ...

    async def route_intent(self, message: str, context: dict[str, Any] | None = None) -> IntentOutput:
        ...

    async def parse_revision(self, message: str, context: dict[str, Any] | None = None) -> RevisionOutput:
        ...


def json_schema(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False)
