from __future__ import annotations

import logging

from google import genai
from google.genai import types

from app.config import Settings

logger = logging.getLogger(__name__)

WEB_TOOL_NAME = "web_ara"

# Anthropic'in sunucu tarafi web_search araci Gemini'de yok. Google Search
# grounding'i ayni istekte fonksiyon cagrilariyla birlikte kullanmak her
# modelde desteklenmiyor; bu yuzden arama, kendi grounded istegini atan ayri
# bir istemci araci olarak calisiyor.
WEB_DECLARATION = types.FunctionDeclaration(
    name=WEB_TOOL_NAME,
    description=(
        "İnternette Google ile arama yapar. Kütüphanede olmayan bir tarifi "
        "bulmak için kullan; bulduğunu tarif_ekle ile aday olarak kaydet."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "sorgu": {"type": "string", "description": "Aranacak şey, örn. 'kore usulü tavuk tarifi'."}
        },
        "required": ["sorgu"],
        "additionalProperties": False,
    },
)


def history_to_contents(history: list[dict]) -> list[types.Content]:
    """ConversationStore'un {"role", "content"} turlarini Gemini'ye cevirir."""
    return [
        types.Content(
            role="model" if turn["role"] == "assistant" else "user",
            parts=[types.Part(text=turn["content"])],
        )
        for turn in history
    ]


def declaration_for(tool) -> types.FunctionDeclaration:
    """Araclar zaten JSON Schema uretiyor; Gemini `parametersJsonSchema` ile
    bunu oldugu gibi kabul ediyor, ayrica OpenAPI alt kumesine cevirmek
    gerekmiyor."""
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters_json_schema=tool.input_schema,
    )


def text_of(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    chunks = [p.text.strip() for p in content.parts if p.text and not p.thought and p.text.strip()]
    return "\n\n".join(chunks).strip()


class GeminiBackend:
    """Ajan dongusunun Gemini (google-genai SDK) uygulamasi.

    Araclar saglayicidan bagimsiz: ayni `MealAgentToolset` nesneleri hem
    Claude hem Gemini yolunda kosuyor; burada yalnizca dongu farkli.
    """

    def __init__(self, settings: Settings, client: genai.Client | None = None):
        self.settings = settings
        self.client = client or genai.Client(
            api_key=settings.gemini_api_key,
            # Ucretsiz katmanin dakikalik siniri dusuk ve bir kullanici mesaji
            # 2-4 istek uretiyor; 429'da kisa beklemeyle tekrar dene.
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(
                    attempts=4,
                    initial_delay=2.0,
                    max_delay=20.0,
                    http_status_codes=[429, 500, 503, 504],
                )
            ),
        )

    @property
    def model(self) -> str:
        return self.settings.gemini_model

    async def run_turn(
        self,
        system_text: str,
        tools: list,
        history: list[dict],
        message: str,
        calls_log: list[str],
    ) -> tuple[str, str | None]:
        """Bir kullanici mesajini sonuna kadar isler.

        (metin, sorun) dondurur; metin bossa `sorun` nedenini tasir.
        """
        by_name = {tool.name: tool for tool in tools}
        declarations = [declaration_for(tool) for tool in tools]
        if self.settings.agent_web_search_enabled:
            declarations.append(WEB_DECLARATION)
        config = types.GenerateContentConfig(
            system_instruction=system_text,
            tools=[types.Tool(function_declarations=declarations)],
            # Donguyu biz yonetiyoruz; SDK'nin otomatik cagrisi Python
            # fonksiyonlari bekliyor, bizim araclarimiz async nesne.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=self.settings.agent_max_tokens,
        )
        contents: list[types.Content] = [
            *history_to_contents(history),
            types.Content(role="user", parts=[types.Part(text=message)]),
        ]
        searches = 0
        last_finish = None
        for _ in range(max(1, self.settings.agent_max_iterations)):
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
            candidate = response.candidates[0] if response.candidates else None
            if candidate is None or candidate.content is None or not candidate.content.parts:
                feedback = getattr(response, "prompt_feedback", None)
                reason = (
                    getattr(candidate, "finish_reason", None)
                    if candidate is not None
                    else getattr(feedback, "block_reason", None)
                )
                return "", f"bos_cevap:{reason}"
            last_finish = candidate.finish_reason
            # Modelin icerigini OLDUGU GIBI geri ekle. Gemini 3 thoughtSignature
            # alanini bu parcalarda tasiyor; eksik gonderilirse sonraki istek
            # 400 ile reddediliyor.
            contents.append(candidate.content)
            calls = [part.function_call for part in candidate.content.parts if part.function_call]
            if not calls:
                return text_of(candidate.content), None

            results: list[types.Part] = []
            for call in calls:
                args = dict(call.args or {})
                if call.name == WEB_TOOL_NAME:
                    calls_log.append(f"web_ara({args.get('sorgu', '')!r})")
                    if searches >= self.settings.agent_web_search_max_uses:
                        result = "Bu turdaki arama sınırına ulaşıldı; elindeki bilgiyle devam et."
                    else:
                        searches += 1
                        result = await self.web_search(str(args.get("sorgu", "")))
                elif call.name in by_name:
                    try:
                        result = await by_name[call.name].call(args)
                    except Exception as error:
                        logger.exception("agent_tool_failed tool=%s", call.name)
                        result = f"Araç hata verdi: {type(error).__name__}: {error}"
                else:
                    result = f"'{call.name}' adında bir araç yok."
                results.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=call.id, name=call.name, response={"result": str(result)}
                        )
                    )
                )
            # Paralel cagrilarin tum sonuclari tek kullanici turunda gider.
            contents.append(types.Content(role="user", parts=results))
        return "", f"adim_siniri:{last_finish}"

    async def web_search(self, query: str) -> str:
        """Ayri bir Google Search grounded istegi; sonucu kaynaklariyla dondurur."""
        if not query.strip():
            return "Arama metni boş."
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=(
                    "Şunu internette ara ve bulduklarını Türkçe, kısaca özetle. "
                    "Bir tarifse adını, miktarlarıyla malzemelerini ve hazırlanışını yaz: "
                    f"{query}"
                ),
                config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
            )
        except Exception as error:
            logger.exception("agent_web_search_failed")
            return f"Arama yapılamadı ({type(error).__name__}). Kullanıcıya söyle, kütüphaneyle devam et."
        candidate = response.candidates[0] if response.candidates else None
        text = text_of(candidate.content) if candidate is not None else ""
        if not text:
            return "Aramadan kullanılabilir bir sonuç çıkmadı."
        sources = []
        metadata = candidate.grounding_metadata if candidate is not None else None
        for chunk in (metadata.grounding_chunks or []) if metadata is not None else []:
            web = chunk.web
            if web is not None and web.uri:
                sources.append(f"- {web.title or web.domain or 'kaynak'}: {web.uri}")
        if sources:
            text += "\n\nKaynaklar:\n" + "\n".join(sources[:5])
        return text

    async def ping(self) -> str:
        response = await self.client.aio.models.generate_content(
            model=self.model, contents="Sadece 'tamam' yaz."
        )
        return text_of(response.candidates[0].content) if response.candidates else ""


def explain_gemini_failure(error: Exception) -> str | None:
    """google-genai hatalarini kullaniciya anlasilir hale getirir."""
    from google.genai import errors

    if not isinstance(error, errors.APIError):
        return None
    code = getattr(error, "code", None)
    status = str(getattr(error, "status", "") or "")
    message = str(getattr(error, "message", "") or error)
    lowered = message.casefold()
    if "api key" in lowered or "api_key" in lowered or code == 401:
        return (
            "Gemini API anahtarı kabul edilmedi. .env içindeki GEMINI_API_KEY "
            "geçersiz ya da silinmiş olabilir; aistudio.google.com'dan yenisini al."
        )
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return (
            "Gemini ücretsiz kotası doldu (dakikalık ya da günlük sınır). "
            "Bir dakika bekleyip tekrar dene; günlük sınırsa yarın sıfırlanır."
        )
    if code == 404 or status == "NOT_FOUND":
        return (
            f"Gemini '{message[:80]}' dedi: model bulunamadı. .env içindeki "
            "GEMINI_MODEL'i gemini-2.5-flash yapmayı dene."
        )
    if code == 403 or status == "PERMISSION_DENIED":
        return "Gemini bu anahtarla isteği reddetti; anahtarın Gemini API için açık olduğunu kontrol et."
    if code is not None and code >= 500:
        return "Gemini tarafında geçici bir sorun var. Birazdan tekrar dener misin?"
    if "location" in lowered and "not supported" in lowered:
        return "Gemini API bu bölgeden kullanılamıyor görünüyor."
    return f"Gemini {code} {status} döndürdü: {message[:200]}"
