from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    admin_telegram_user_id: int | None = None
    telegram_recipient_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    timezone: str = "Europe/Istanbul"
    weekly_plan_day: str = "sunday"
    weekly_plan_time: str = "10:00"

    database_url: str = "sqlite:///data/mealplanner.db"

    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    default_servings: int = 4
    meal_slots: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["dinner"])
    meal_course_roles: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["main", "meze", "meze", "side"])
    courses_per_day: int = 3
    pantry_mode: Literal["exclude", "check"] = "exclude"
    log_level: str = "INFO"

    recipe_discovery_enabled: bool = True
    recipe_discovery_day: str = "saturday"
    recipe_discovery_time: str = "18:00"
    recipe_discovery_limit_per_category: int = 2
    recipe_discovery_queries: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "Güncel, sağlıklı, sıradışı ama evde yapılabilir ana yemek önerileri. category=main meal_type=dinner",
            "Güncel, sağlıklı, sıradışı yan yemek önerileri: çorba, kinoa, bulgur, pilav, makarna, sebze. category=side meal_type=dinner",
            "Modern meyhane tarzı sağlıklı meze veya salata önerileri. category=meze_or_salad meal_type=dinner",
        ]
    )

    web_panel_enabled: bool = True
    web_panel_host: str = "127.0.0.1"
    web_panel_port: int = 8000
    web_panel_token: str = ""

    data_dir: Path = Path("data")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("telegram_recipient_chat_ids", mode="before")
    @classmethod
    def parse_chat_ids(cls, value: str | list[int] | None) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(v) for v in value]
        return [int(part.strip()) for part in value.split(",") if part.strip()]

    @field_validator("meal_slots", mode="before")
    @classmethod
    def parse_slots(cls, value: str | list[str] | None) -> list[str]:
        if value is None or value == "":
            return ["dinner"]
        if isinstance(value, list):
            return value
        return [part.strip() for part in value.split(",") if part.strip()]

    @field_validator("meal_course_roles", mode="before")
    @classmethod
    def parse_course_roles(cls, value: str | list[str] | None) -> list[str]:
        if value is None or value == "":
            return ["main", "meze", "meze", "side"]
        if isinstance(value, list):
            return value
        return [part.strip().casefold() for part in value.split(",") if part.strip()]

    @field_validator("recipe_discovery_queries", mode="before")
    @classmethod
    def parse_discovery_queries(cls, value: str | list[str] | None) -> list[str]:
        if value is None or value == "":
            return [
                "Güncel, sağlıklı, sıradışı ama evde yapılabilir ana yemek önerileri. category=main meal_type=dinner",
                "Güncel, sağlıklı, sıradışı yan yemek önerileri: çorba, kinoa, bulgur, pilav, makarna, sebze. category=side meal_type=dinner",
                "Modern meyhane tarzı sağlıklı meze veya salata önerileri. category=meze_or_salad meal_type=dinner",
            ]
        if isinstance(value, list):
            return value
        separator = ";" if ";" in value else "|"
        return [part.strip() for part in value.split(separator) if part.strip()]

    @property
    def all_recipient_ids(self) -> list[int]:
        ids = list(self.telegram_recipient_chat_ids)
        if self.admin_telegram_user_id is not None and self.admin_telegram_user_id not in ids:
            ids.insert(0, self.admin_telegram_user_id)
        return ids

    @property
    def planning_slots(self) -> list[str]:
        if self.meal_course_roles:
            slots: list[str] = []
            for meal_slot in self.meal_slots:
                seen: dict[str, int] = {}
                for role in self.meal_course_roles:
                    seen[role] = seen.get(role, 0) + 1
                    suffix = role if self.meal_course_roles.count(role) == 1 else f"{role}_{seen[role]}"
                    slots.append(f"{meal_slot}_{suffix}")
            return slots
        if self.courses_per_day <= 1:
            return self.meal_slots
        return [f"{slot}_{course}" for slot in self.meal_slots for course in range(1, self.courses_per_day + 1)]


def base_meal_slot(slot: str) -> str:
    if "_" in slot:
        return slot.split("_", 1)[0]
    base, separator, suffix = slot.rpartition("_")
    if separator and suffix.isdigit():
        return base
    return slot


def course_role(slot: str) -> str:
    if "_" not in slot:
        return "main"
    role = slot.split("_", 1)[1]
    base, separator, suffix = role.rpartition("_")
    if separator and suffix.isdigit():
        return base
    if role.isdigit():
        return "main"
    return role


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
