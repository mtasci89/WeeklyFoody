from __future__ import annotations

from app.config import Settings
from app.llm import build_llm_provider
from app.llm.base import IntentOutput


class NaturalLanguageRouter:
    def __init__(self, settings: Settings):
        self.llm = build_llm_provider(settings)

    async def route(self, message: str, context: dict | None = None) -> IntentOutput:
        return await self.llm.route_intent(message, context or {})

