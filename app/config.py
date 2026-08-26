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
    pantry_mode: Literal["exclude", "check"] = "exclude"
    log_level: str = "INFO"

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

    @property
    def all_recipient_ids(self) -> list[int]:
        ids = list(self.telegram_recipient_chat_ids)
        if self.admin_telegram_user_id is not None and self.admin_telegram_user_id not in ids:
            ids.insert(0, self.admin_telegram_user_id)
        return ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
