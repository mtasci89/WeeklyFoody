from __future__ import annotations

import logging

from app.config import Settings
from app.llm.base import IntentOutput, LLMProvider, RevisionOutput, WeeklyPlanOutput
from app.llm.gemini import GeminiLLMProvider
from app.llm.openai import OpenAILLMProvider
from app.llm.rule_based import RuleBasedLLMProvider

logger = logging.getLogger(__name__)


class FallbackLLMProvider:
    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary = primary
        self.fallback = fallback

    async def generate_plan(self, context: dict) -> WeeklyPlanOutput:
        try:
            return await self.primary.generate_plan(context)
        except Exception as exc:
            logger.warning("llm_primary_failed operation=generate_plan fallback=rule_based error=%s", exc.__class__.__name__)
            return await self.fallback.generate_plan(context)

    async def route_intent(self, message: str, context: dict | None = None) -> IntentOutput:
        try:
            return await self.primary.route_intent(message, context)
        except Exception as exc:
            logger.warning("llm_primary_failed operation=route_intent fallback=rule_based error=%s", exc.__class__.__name__)
            return await self.fallback.route_intent(message, context)

    async def parse_revision(self, message: str, context: dict | None = None) -> RevisionOutput:
        try:
            return await self.primary.parse_revision(message, context)
        except Exception as exc:
            logger.warning("llm_primary_failed operation=parse_revision fallback=rule_based error=%s", exc.__class__.__name__)
            return await self.fallback.parse_revision(message, context)

    async def answer_general_question(self, message: str, context: dict | None = None) -> str:
        try:
            return await self.primary.answer_general_question(message, context)
        except Exception as exc:
            logger.warning("llm_primary_failed operation=answer_general_question fallback=rule_based error=%s", exc.__class__.__name__)
            return await self.fallback.answer_general_question(message, context)


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        return FallbackLLMProvider(GeminiLLMProvider(settings), RuleBasedLLMProvider())
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return FallbackLLMProvider(OpenAILLMProvider(settings), RuleBasedLLMProvider())
    return RuleBasedLLMProvider()
