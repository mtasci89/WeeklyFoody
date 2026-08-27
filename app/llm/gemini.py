from __future__ import annotations

import json
import re
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings
from app.llm.base import IntentOutput, LLMProvider, RevisionOutput, WeeklyPlanOutput, json_schema

T = TypeVar("T", bound=BaseModel)


class GeminiLLMProvider(LLMProvider):
    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for Gemini provider")
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3))
    async def _structured(self, system: str, user: str, schema_model: type[T]) -> T:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": f"{user}\n\nReturn JSON matching this schema only:\n{json_schema(schema_model)}"}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        text = data["candidates"][0]["content"]["parts"][0].get("text", "{}")
        return schema_model.model_validate(json.loads(_extract_json(text)))

    async def generate_plan(self, context: dict[str, Any]) -> WeeklyPlanOutput:
        return await self._structured(
            "You are a Turkish-speaking weekly meal planning assistant. Use only supplied recipe IDs.",
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
        url = f"{self.base_url}/models/{self.model}:generateContent"
        payload = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "Türkçe konuşan, kısa ve pratik cevap veren bir aile yemek planlama botusun. "
                            "Basit yemek, tarif, menü, alışveriş listesi ve bot kullanımı sorularını cevapla. "
                            "Kullanıcı bir işlem yapmak istiyorsa yapılabilecek doğal dil örnekleri ver; işlem yapmış gibi davranma. "
                            "Konu yemek planlama dışına çıkarsa kibarca kendi alanına döndür."
                        )
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps({"message": message, "context": context or {}}, ensure_ascii=False)}],
                }
            ],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 500},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return data["candidates"][0]["content"]["parts"][0].get("text", "").strip() or "Bu konuda yardımcı olabilirim; biraz daha açar mısın?"


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if match:
        return match.group(1)
    return stripped
