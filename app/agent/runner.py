from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent.conversation import ConversationStore
from app.agent.prompts import SYSTEM_PROMPT, context_block
from app.agent.tools import MealAgentToolset, SessionFactory
from app.config import Settings

logger = logging.getLogger(__name__)

FALLBACK_SUFFIX = " Bu arada /menu, /shopping ve /regenerate komutları çalışmaya devam ediyor."

FALLBACK_REPLY = (
    "Şu an isteğini işleyemedim, teknik bir aksilik oldu. Birazdan tekrar dener misin?"
    + FALLBACK_SUFFIX
)


def explain_failure(error: Exception) -> str:
    """Hatanin SEBEBINI kullaniciya soyler.

    Tek bir "teknik aksilik" mesaji her arizayi ayni gosteriyordu: bitmis
    kredi, yanlis anahtar ve gecici kesinti arasinda fark yoktu, kullanici
    neyi duzeltecegini bilemiyordu.
    """
    from app.agent.gemini_backend import explain_gemini_failure

    gemini = explain_gemini_failure(error)
    if gemini is not None:
        return gemini

    import anthropic

    if isinstance(error, anthropic.AuthenticationError):
        return (
            "Anthropic API anahtarı kabul edilmedi. .env içindeki "
            "ANTHROPIC_API_KEY geçersiz ya da silinmiş olabilir."
        )
    if isinstance(error, anthropic.PermissionDeniedError):
        return (
            "Anthropic hesabı bu isteği reddetti. Genellikle bakiye bitmiş ya da "
            "harcama limitine takılmış olur; faturalandırma sayfasını kontrol et."
        )
    if isinstance(error, anthropic.RateLimitError):
        return "Anthropic hız sınırına takıldım. Bir dakika bekleyip tekrar dener misin?"
    if isinstance(error, (anthropic.OverloadedError, anthropic.InternalServerError,
                          anthropic.ServiceUnavailableError)):
        return "Anthropic tarafında geçici bir sorun var. Birazdan tekrar dener misin?"
    if isinstance(error, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return "Anthropic'e ulaşamadım; internet bağlantısı ya da ağ sorunu olabilir."
    if isinstance(error, anthropic.BadRequestError):
        return (
            "İstek Anthropic tarafından reddedildi (geçersiz istek). "
            f"Ayrıntı: {str(error)[:200]}"
        )
    if isinstance(error, anthropic.APIStatusError):
        return f"Anthropic {getattr(error, 'status_code', '?')} döndürdü: {str(error)[:200]}"
    return f"Beklenmedik bir hata: {type(error).__name__}: {str(error)[:200]}"


@dataclass
class Gorsel:
    """Mesaja eklenen bir görsel (fotoğraf, ekran görüntüsü)."""

    mime: str
    data: bytes


GORSEL_TURLERI = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
VARSAYILAN_GORSEL_MESAJI = "Bu görsele bak ve ne yapabileceğini söyle."


@dataclass
class AgentReply:
    text: str
    tool_calls: list[str] = field(default_factory=list)
    ok: bool = True
    # Bu turda plani okunan/degistirilen hafta (WeeklyPlanningSession.id).
    plan_session_id: str | None = None


class MealPlannerAgent:
    """Tool-use dongusu uzerine kurulu konusma ajani.

    Eski `NaturalLanguageRouter`in yerini alir: orada model mesaji 18 degerli
    bir enuma esliyordu ve isi sabit bir `if` zinciri yapiyordu. Burada model
    araclari kendisi secip sirayla cagiriyor, sonra cevabini kendisi yaziyor.

    Araclar saglayicidan bagimsiz; `AGENT_PROVIDER` yalnizca donguyu kimin
    kosturacagini secer (Gemini ya da Claude).
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: SessionFactory,
        client=None,
        store: ConversationStore | None = None,
        notifier=None,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.notifier = notifier
        self.provider = settings.agent_provider
        self.store = store or ConversationStore(max_turns=settings.agent_history_turns)
        if self.provider == "gemini":
            from app.agent.gemini_backend import GeminiBackend

            self.gemini = GeminiBackend(settings, client=client)
            self.client = self.gemini.client
        elif client is not None:
            self.client = client
        else:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    def estimator(self):
        """Eksik kalori/protein degerlerini tahmin eden yardimci (yalnizca Gemini)."""
        if self.provider != "gemini":
            return None
        from app.agent.nutrition import NutritionEstimator

        return NutritionEstimator(self.gemini.generate_json)

    @classmethod
    def available(cls, settings: Settings) -> bool:
        if not settings.agent_enabled:
            return False
        if settings.agent_provider == "gemini":
            return bool(settings.gemini_api_key)
        return bool(settings.anthropic_api_key)

    @property
    def model(self) -> str:
        return self.settings.gemini_model if self.provider == "gemini" else self.settings.anthropic_model

    def _context(self, toolset: MealAgentToolset) -> str:
        hard, soft, pantry = toolset.ambient_context()
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        return context_block(today, toolset.plan_summary(), hard, soft, pantry)

    async def aclose(self) -> None:
        """Istemcinin ag oturumunu kapatir (kisa omurlu kullanim icin: CLI)."""
        closer = getattr(getattr(self.client, "aio", None), "aclose", None) or getattr(self.client, "close", None)
        if closer is None:
            return
        result = closer()
        if hasattr(result, "__await__"):
            await result

    async def ping(self) -> str:
        """Saglayiciya tek, kucuk bir istek atar. Kurulumu dogrulamak icin."""
        if self.provider == "gemini":
            return await self.gemini.ping()
        response = await self.client.messages.create(
            model=self.settings.anthropic_model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Sadece 'tamam' yaz."}],
        )
        return _text_of(response)

    def _betas(self) -> list[str]:
        """1 saatlik onbellek TTL'i beta basligi ister; 5 dakikalik istemez."""
        return ["extended-cache-ttl-2025-04-11"] if self.settings.agent_cache_ttl == "1h" else []

    def _tools(self, toolset: MealAgentToolset) -> list:
        """Kendi araclarimiz + Anthropic'in sunucu tarafi web arama araci.

        Sunucu araclarinin calistiracak bir fonksiyonu yoktur; ham tanim
        olarak gecilir ve Anthropic tarafinda kosar.
        """
        tools = toolset.build()
        if self.settings.agent_web_search_enabled:
            tools.append(
                {
                    "type": "web_search_20260209",
                    "name": "web_search",
                    "max_uses": self.settings.agent_web_search_max_uses,
                }
            )
        return tools

    def _system(self, toolset: MealAgentToolset) -> list[dict]:
        return [
            # Sabit kisim onbellege alinir; arac semalari da bu on-ekin
            # parcasi oldugu icin her istekte yeniden faturalanmaz.
            # Sabit on-ek (arac semalari + sistem istemi) ~4.000 token ve
            # bir kullanici mesaji 2-4 istek uretiyor; onbellekten okumak
            # tam fiyatin cok altinda. "1h" beta basligi ister, "5m" istemez.
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": self.settings.agent_cache_ttl},
            },
            {"type": "text", "text": self._context(toolset)},
        ]

    async def reply(
        self, chat_id: int, message: str, images: list[Gorsel] | None = None, timeout: int | None = None
    ) -> AgentReply:
        images = list(images or [])
        message = message.strip() or (VARSAYILAN_GORSEL_MESAJI if images else message)
        logger.info(
            "agent_turn_started chat_id=%s provider=%s model=%s images=%s",
            chat_id, self.provider, self.model, len(images),
        )
        toolset = MealAgentToolset(
            self.settings, self.session_factory, estimator=self.estimator(), notifier=self.notifier
        )
        limit = timeout or self.settings.agent_turn_timeout_seconds
        try:
            return await asyncio.wait_for(
                self._reply(chat_id, message, toolset, images),
                timeout=limit,
            )
        except asyncio.TimeoutError:
            logger.warning("agent_turn_timeout chat_id=%s seconds=%s tools=%s", chat_id, limit, toolset.calls)
            return AgentReply(
                text=(
                    f"Bu istek {limit} saniyeden uzun sürdü, "
                    "yarıda bıraktım. Daha kısa bir şey isteyerek tekrar dener misin?"
                    + FALLBACK_SUFFIX
                ),
                tool_calls=toolset.calls,
                ok=False,
            )

    async def _reply(
        self, chat_id: int, message: str, toolset: MealAgentToolset, images: list[Gorsel]
    ) -> AgentReply:
        history = self.store.history(chat_id)
        if self.provider == "gemini":
            return await self._reply_gemini(chat_id, message, toolset, history, images)
        content: str | list = message
        if images:
            content = [
                *(
                    {"type": "image", "source": {"type": "base64", "media_type": g.mime,
                                                 "data": base64.b64encode(g.data).decode()}}
                    for g in images
                ),
                {"type": "text", "text": message},
            ]
        messages: list = [*history, {"role": "user", "content": content}]
        system = self._system(toolset)
        tools = self._tools(toolset)
        betas = self._betas()
        try:
            final = None
            restarts = 0
            while True:
                runner = self.client.beta.messages.tool_runner(
                    model=self.settings.anthropic_model,
                    max_tokens=self.settings.agent_max_tokens,
                    max_iterations=self.settings.agent_max_iterations,
                    system=system,
                    tools=tools,
                    # Kopya: asagida `messages` aynalama icin buyuyor, verilen
                    # istek o buyumeden geriye donuk etkilenmemeli.
                    messages=list(messages),
                    output_config={"effort": self.settings.agent_effort},
                    **({"betas": betas} if betas else {}),
                )
                last = None
                async for response in runner:
                    last = response
                    # Runner kendi kopyasini tutar ve disari vermez; tur
                    # `pause_turn` ile durursa kaldigi yerden devam
                    # edebilmek icin gecmisi burada aynaliyoruz.
                    messages.append({"role": "assistant", "content": response.content})
                    tool_response = await runner.generate_tool_call_response()
                    if tool_response is not None:
                        messages.append(tool_response)
                final = last or final
                if last is None or getattr(last, "stop_reason", None) != "pause_turn":
                    break
                restarts += 1
                if restarts > self.settings.agent_max_pause_restarts:
                    logger.warning("agent_pause_turn_giving_up chat_id=%s restarts=%s", chat_id, restarts)
                    break
                logger.info("agent_pause_turn_resumed chat_id=%s restart=%s", chat_id, restarts)
            text = _text_of(final)
        except Exception as error:
            logger.exception("agent_turn_failed chat_id=%s", chat_id)
            return AgentReply(
                text=explain_failure(error) + FALLBACK_SUFFIX,
                tool_calls=toolset.calls,
                ok=False,
            )

        return self._finish(chat_id, message, text, toolset, getattr(final, "stop_reason", None), len(images))

    async def _reply_gemini(
        self, chat_id: int, message: str, toolset: MealAgentToolset, history: list[dict], images: list[Gorsel]
    ) -> AgentReply:
        from app.agent.prompts import for_provider

        system_text = for_provider(SYSTEM_PROMPT, "gemini") + "\n\n" + self._context(toolset)
        try:
            text, problem = await self.gemini.run_turn(
                system_text, toolset.build(), history, message, toolset.calls,
                images=[(g.mime, g.data) for g in images],
            )
        except Exception as error:
            logger.exception("agent_turn_failed chat_id=%s", chat_id)
            return AgentReply(
                text=explain_failure(error) + FALLBACK_SUFFIX,
                tool_calls=toolset.calls,
                ok=False,
            )
        return self._finish(chat_id, message, text, toolset, problem, len(images))

    def _finish(
        self, chat_id: int, message: str, text: str, toolset: MealAgentToolset, stop: object, image_count: int = 0
    ) -> AgentReply:
        if not text:
            logger.warning(
                "agent_empty_reply chat_id=%s stop=%s tools=%s", chat_id, stop, toolset.calls
            )
            return AgentReply(
                text="Bunu anlayamadım, biraz daha açar mısın?",
                tool_calls=toolset.calls,
                ok=False,
            )

        # Gorseller gecmise yazilmaz (buyuk ve tekrar gonderilmesi gereksiz);
        # sonraki mesajlarda "o listedeki" diye donulebilsin diye notu kalir.
        note = f" [{image_count} görsel eklenmişti]" if image_count else ""
        self.store.record(chat_id, "user", message + note)
        self.store.record(chat_id, "assistant", text)
        logger.info("agent_turn chat_id=%s tool_calls=%s", chat_id, len(toolset.calls))
        if toolset.calls:
            logger.info("agent_tools chat_id=%s calls=%s", chat_id, " | ".join(toolset.calls))
        return AgentReply(text=text, tool_calls=toolset.calls, plan_session_id=toolset.touched_session_id)


def _text_of(response) -> str:
    if response is None:
        return ""
    chunks = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text" and getattr(block, "text", "").strip()
    ]
    return "\n\n".join(chunk.strip() for chunk in chunks).strip()
