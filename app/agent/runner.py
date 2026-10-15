from __future__ import annotations

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
class AgentReply:
    text: str
    tool_calls: list[str] = field(default_factory=list)
    ok: bool = True


class MealPlannerAgent:
    """Claude tool-use dongusu uzerine kurulu konusma ajani.

    Eski `NaturalLanguageRouter`in yerini alir: orada model mesaji 18 degerli
    bir enuma esliyordu ve isi sabit bir `if` zinciri yapiyordu. Burada model
    araclari kendisi secip sirayla cagiriyor, sonra cevabini kendisi yaziyor.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: SessionFactory,
        client=None,
        store: ConversationStore | None = None,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.store = store or ConversationStore(max_turns=settings.agent_history_turns)
        if client is not None:
            self.client = client
        else:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    @classmethod
    def available(cls, settings: Settings) -> bool:
        return bool(settings.agent_enabled and settings.anthropic_api_key)

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
        hard, soft, pantry = toolset.ambient_context()
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
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
            {
                "type": "text",
                "text": context_block(today, toolset.plan_summary(), hard, soft, pantry),
            },
        ]

    async def reply(self, chat_id: int, message: str) -> AgentReply:
        toolset = MealAgentToolset(self.settings, self.session_factory)
        history = self.store.history(chat_id)
        messages: list = [*history, {"role": "user", "content": message}]
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

        if not text:
            logger.warning(
                "agent_empty_reply chat_id=%s stop_reason=%s tools=%s",
                chat_id,
                getattr(final, "stop_reason", None),
                toolset.calls,
            )
            return AgentReply(
                text="Bunu anlayamadım, biraz daha açar mısın?",
                tool_calls=toolset.calls,
                ok=False,
            )

        self.store.record(chat_id, "user", message)
        self.store.record(chat_id, "assistant", text)
        logger.info("agent_turn chat_id=%s tool_calls=%s", chat_id, len(toolset.calls))
        if toolset.calls:
            logger.info("agent_tools chat_id=%s calls=%s", chat_id, " | ".join(toolset.calls))
        return AgentReply(text=text, tool_calls=toolset.calls)


def _text_of(response) -> str:
    if response is None:
        return ""
    chunks = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text" and getattr(block, "text", "").strip()
    ]
    return "\n\n".join(chunk.strip() for chunk in chunks).strip()
