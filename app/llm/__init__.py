from __future__ import annotations

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.openai import OpenAILLMProvider
from app.llm.rule_based import RuleBasedLLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return OpenAILLMProvider(settings)
    return RuleBasedLLMProvider()

