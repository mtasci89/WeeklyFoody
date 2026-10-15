from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from google import genai
from google.genai import errors, types

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


# Baska modele gecmeyi hakli kilan hatalar: model mesgul, modelin kotasi dolmus
# ya da model kapatilmis. Anahtar/yetki hatalari (400/401/403) tum modeller icin
# ayni oldugundan gecis yapmaz; dogrudan kullaniciya aciklanir.
FALLBACK_CODES = {404, 429, 500, 503, 504}


def should_fall_back(error: Exception) -> bool:
    return isinstance(error, errors.APIError) and getattr(error, "code", None) in FALLBACK_CODES


@dataclass
class ModelCursor:
    """Bir tur boyunca hangi modelde oldugumuz. Yapiskan: tur icinde bir kez
    yedege gecildiyse geri donulmez, cunku onceki adimlarin thoughtSignature
    alanlari o modelin urettigi parcalarda duruyor."""

    index: int = 0


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
                # Milisaniye. Asili kalan bir istek turu sonsuza dek bekletmesin.
                timeout=settings.agent_request_timeout_seconds * 1000,
                # Kisa tutuldu: model mesgulse uzun beklemek yerine yedek
                # modele gecmek daha hizli cevap getiriyor.
                retry_options=types.HttpRetryOptions(
                    attempts=3,
                    initial_delay=2.0,
                    max_delay=8.0,
                    http_status_codes=[429, 500, 503, 504],
                )
            ),
        )

    @property
    def model(self) -> str:
        return self.settings.gemini_model

    @property
    def models(self) -> list[str]:
        """Ana model + yedekler, tekrarsiz ve sirali."""
        chain: list[str] = []
        for name in [self.settings.gemini_model, *self.settings.gemini_fallback_models]:
            if name and name not in chain:
                chain.append(name)
        return chain

    async def _generate(self, cursor: ModelCursor, contents, config=None):
        """Zincirdeki ilk calisan modelle istek atar."""
        models = self.models
        last_error: Exception | None = None
        for index in range(cursor.index, len(models)):
            model = models[index]
            try:
                response = await self.client.aio.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as error:
                if not should_fall_back(error) or index == len(models) - 1:
                    raise
                logger.warning(
                    "agent_model_unavailable model=%s code=%s next=%s",
                    model, getattr(error, "code", None), models[index + 1],
                )
                last_error = error
                continue
            if index != cursor.index:
                logger.warning("agent_model_fallback from=%s to=%s", models[cursor.index], model)
                cursor.index = index
            return response
        raise last_error if last_error else RuntimeError("Denenecek Gemini modeli yok")

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
        cursor = ModelCursor()
        for step in range(1, max(1, self.settings.agent_max_iterations) + 1):
            # Her adim terminalde gorunsun: uzun bir plan turu disaridan
            # "bot oldu" gibi gorunmesin.
            logger.info("agent_model_request step=%s model=%s", step, self.models[cursor.index])
            response = await self._generate(cursor, contents, config)
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
                logger.info("agent_tool_call step=%s tool=%s", step, call.name)
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
            response = await self._generate(
                ModelCursor(),
                (
                    "Şunu internette ara ve bulduklarını Türkçe, kısaca özetle. "
                    "Bir tarifse adını, miktarlarıyla malzemelerini ve hazırlanışını yaz: "
                    f"{query}"
                ),
                types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
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
        response = await self._generate(ModelCursor(), "Sadece 'tamam' yaz.")
        return text_of(response.candidates[0].content) if response.candidates else ""

    async def check_models(self) -> list[tuple[str, bool, str]]:
        """Zincirdeki HER modeli tek tek dener: (model, calisiyor_mu, aciklama)."""
        results = []
        for model in self.models:
            try:
                response = await self.client.aio.models.generate_content(
                    model=model, contents="Sadece 'tamam' yaz."
                )
                answer = text_of(response.candidates[0].content) if response.candidates else ""
                results.append((model, True, f"cevap: {answer[:30]!r}"))
            except Exception as error:
                results.append((model, False, model_status(error)))
        return results


def model_status(error: Exception) -> str:
    """check-agent tablosu icin kisa durum."""
    code = getattr(error, "code", None)
    labels = {404: "BULUNAMADI (model yok/kapatilmis)", 429: "KOTA DOLU", 503: "MESGUL (asiri yuk)"}
    if code in labels:
        return labels[code]
    return explain_gemini_failure(error) or f"{type(error).__name__}: {str(error)[:80]}"


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
        # Sabit bir model onermiyoruz: eskiden burada gemini-2.5-flash yaziyordu
        # ve tam da kapatilan model oydu. API cogu zaman yerine geceni soyluyor.
        suggested = re.search(r"use (?:models/)?(gemini-[\w.\-]+)", message)
        if suggested:
            return (
                "Gemini bu modeli artık sunmuyor. Google'ın önerdiği model: "
                f"{suggested.group(1)}. .env içine GEMINI_MODEL={suggested.group(1)} yaz."
            )
        return (
            "Gemini modeli bulunamadı. .env içindeki GEMINI_MODEL geçerli bir "
            f"model adı olmalı. Google'ın mesajı: {message[:300]}"
        )
    if code == 403 or status == "PERMISSION_DENIED":
        return "Gemini bu anahtarla isteği reddetti; anahtarın Gemini API için açık olduğunu kontrol et."
    if code is not None and code >= 500:
        return (
            "Gemini modelleri şu an aşırı yoğun (yedek modeller dahil). "
            "Birkaç dakika sonra tekrar dener misin?"
        )
    if "location" in lowered and "not supported" in lowered:
        return "Gemini API bu bölgeden kullanılamıyor görünüyor."
    return f"Gemini {code} {status} döndürdü: {message[:200]}"
