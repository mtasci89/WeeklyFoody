from __future__ import annotations

import json
from typing import Any, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings
from app.llm.base import IntentOutput, LLMProvider, RevisionOutput, WeeklyPlanOutput, json_schema

T = TypeVar("T", bound=BaseModel)


class OpenAILLMProvider(LLMProvider):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3))
    async def _structured(self, system: str, user: str, schema_model: type[T]) -> T:
        schema = json_schema(schema_model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"{user}\n\nReturn JSON matching this schema only:\n{schema}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        return schema_model.model_validate(json.loads(content))

    async def generate_plan(self, context: dict[str, Any]) -> WeeklyPlanOutput:
        return await self._structured(
            (
                "You are a Turkish-speaking weekly meal planning assistant. Use only supplied recipe IDs. "
                "Respect slot_requirements exactly: main slots need one main dish, meze slots need meze/salad dishes, "
                "and side slots need soup, pilaf, pasta, quinoa, grain, or other side dishes. Prefer candidate_recipes_by_slot."
            ),
            json.dumps(context, ensure_ascii=False),
            WeeklyPlanOutput,
        )

    async def route_intent(self, message: str, context: dict[str, Any] | None = None) -> IntentOutput:
        return await self._structured(
            "Classify Turkish Telegram meal-planner messages. Ask clarification if a permanent rule is ambiguous.",
            json.dumps({"message": message, "context": context or {}}, ensure_ascii=False),
            IntentOutput,
        )

    async def parse_revision(self, message: str, context: dict[str, Any] | None = None) -> RevisionOutput:
        return await self._structured(
            "Extract minimal meal-plan revision operations from Turkish text. Preserve unaffected days.",
            json.dumps({"message": message, "context": context or {}}, ensure_ascii=False),
            RevisionOutput,
        )

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3))
    async def answer_general_question(self, message: str, context: dict[str, Any] | None = None) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Türkçe konuşan, kısa ve pratik cevap veren bir aile yemek planlama botusun. "
                        "Basit yemek, tarif, menü, alışveriş listesi ve bot kullanımı sorularını cevapla. "
                        "Kullanıcı bir işlem yapmak istiyorsa yapılabilecek doğal dil örnekleri ver; işlem yapmış gibi davranma. "
                        "Konu yemek planlama dışına çıkarsa kibarca kendi alanına döndür."
                    ),
                },
                {"role": "user", "content": json.dumps({"message": message, "context": context or {}}, ensure_ascii=False)},
            ],
            temperature=0.4,
        )
        return (response.choices[0].message.content or "").strip() or "Bu konuda yardımcı olabilirim; biraz daha açar mısın?"
