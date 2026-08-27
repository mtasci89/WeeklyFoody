from __future__ import annotations

from app.config import Settings
from app.llm import build_llm_provider
from app.llm.base import Intent, IntentOutput
from app.llm.rule_based import RuleBasedLLMProvider


class NaturalLanguageRouter:
    def __init__(self, settings: Settings):
        self.llm = build_llm_provider(settings)
        self.rules = RuleBasedLLMProvider()

    async def route(self, message: str, context: dict | None = None) -> IntentOutput:
        rule_result = await self.rules.route_intent(message, context or {})
        if rule_result.intent not in {Intent.UNKNOWN, Intent.GENERAL_QUESTION} and rule_result.confidence >= 0.88:
            return rule_result
        llm_result = await self.llm.route_intent(message, context or {})
        if llm_result.intent in {Intent.UNKNOWN, Intent.GENERAL_QUESTION} and rule_result.intent != Intent.UNKNOWN:
            return rule_result
        return llm_result

    async def answer_general_question(self, message: str, context: dict | None = None) -> str:
        return await self.llm.answer_general_question(message, context or {})
