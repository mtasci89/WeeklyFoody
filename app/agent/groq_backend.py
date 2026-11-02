"""Groq (OpenAI uyumlu API) ile asistan döngüsü ve yapılandırılmış istekler.

Kullanıcı: "Google hiç kullanma, yalnızca Groq ve Tavily." Groq'un ücretsiz katmanı
dakikalık token sınırı düşük (model başına ~6-12 bin token/dakika) ama modelleri
çok ve her modelin sınırı ayrı. Bu yüzden:
- istekler küçük tutulur (kısa sistem istemi, kısa araç açıklamaları, eski araç
  sonuçları kısaltılır),
- sınıra takılan model, Groq'un söylediği süre kadar atlanır ve sıradaki modele
  geçilir; hepsi doluysa en yakın açılış beklenir (iş arka planda, uygulama
  bekleyebilir).
GeminiBackend ile aynı yüzeyi sunar: run_turn, generate_json, search_text,
web_search, ping, check_models, check_search.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from types import SimpleNamespace

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
WEB_TOOL_NAME = "web_ara"
# Tüm modeller doluyken en fazla bu kadar beklenir (saniye); daha uzunsa hata verilir.
MAX_POOL_WAIT = 65
TOOL_RESULT_CHARS = 3500
OLD_TOOL_RESULT_CHARS = 500
HISTORY_TURNS = 8
HISTORY_CHARS = 1200
TOOL_DESCRIPTION_CHARS = 420


class GroqError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, retry_after: float | None = None, kind: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.kind = kind


def _retry_after(response: httpx.Response, message: str) -> float | None:
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", message)
    if match:
        return float(match.group(1) or 0) * 60 + float(match.group(2))
    return None


def short_description(text: str) -> str:
    """Araç açıklamasının ilk paragrafı (Groq'un token sınırı için)."""
    first = (text or "").strip().split("\n\n")[0]
    first = " ".join(first.split())
    return first[:TOOL_DESCRIPTION_CHARS]


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


WEB_SPEC = {
    "type": "function",
    "function": {
        "name": WEB_TOOL_NAME,
        "description": "İnternette (Tavily) tarif arar; sayfa metinlerini ve kaynak bağlantılarını döndürür.",
        "parameters": {"type": "object", "properties": {"sorgu": {"type": "string"}}, "required": ["sorgu"]},
    },
}


class GroqBackend:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None, tavily=None):
        self.settings = settings
        self.http = http or httpx.AsyncClient(timeout=settings.agent_request_timeout_seconds)
        if tavily is None and settings.tavily_api_key:
            from app.agent.tavily import TavilySearch
            tavily = TavilySearch(settings.tavily_api_key)
        self.tavily = tavily
        self._cooldown_until: dict[str, float] = {}
        self.search_client = None  # GeminiBackend ile uyum
        # runner/cli `client.aio.aclose()` çağırır.
        self.client = SimpleNamespace(aio=SimpleNamespace(aclose=self.aclose))

    @property
    def models(self) -> list[str]:
        return list(dict.fromkeys(m for m in self.settings.groq_models if m))

    async def aclose(self) -> None:
        await self.http.aclose()
        if self.tavily is not None:
            await self.tavily.aclose()

    # --- istek --------------------------------------------------------------

    async def _post(self, model: str, body: dict) -> dict:
        response = await self.http.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
            json={**body, "model": model},
        )
        if response.status_code == 200:
            return response.json()
        try:
            error = response.json().get("error") or {}
        except ValueError:
            error = {}
        message = str(error.get("message") or response.text[:300])
        raise GroqError(message, response.status_code, _retry_after(response, message), str(error.get("code") or error.get("type") or ""))

    async def _chat(self, messages: list[dict], *, tools: list | None = None, json_mode: bool = False,
                    vision: bool = False, max_tokens: int | None = None) -> tuple[dict, str]:
        chain = [self.settings.groq_vision_model] if vision else self.models
        body: dict = {"messages": messages, "temperature": 0.6,
                      "max_completion_tokens": max_tokens or min(self.settings.agent_max_tokens, 4096)}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        last: Exception | None = None
        for _ in range(4):  # havuz turu: hepsi doluysa bekle, tekrar dene
            for model in chain:
                if self._cooldown_until.get(model, 0) > time.monotonic():
                    continue
                try:
                    data = await self._post(model, body)
                except GroqError as error:
                    last = error
                    if error.code == 429:
                        wait = error.retry_after or 60
                        self._cooldown_until[model] = time.monotonic() + wait
                        logger.warning("groq_model_limited model=%s wait=%.0f kind=%s", model, wait, error.kind)
                        continue
                    if error.code == 413:  # bu modelin dakikalık sınırına tek istek sığmıyor
                        logger.warning("groq_request_too_large model=%s", model)
                        continue
                    if error.code in (404, 403) or (error.code == 400 and "decommission" in error.message.lower()):
                        self._cooldown_until[model] = time.monotonic() + 6 * 3600
                        logger.warning("groq_model_unavailable model=%s code=%s", model, error.code)
                        continue
                    if error.code == 400 and error.kind in {"tool_use_failed", "json_validate_failed"}:
                        logger.warning("groq_bad_generation model=%s kind=%s", model, error.kind)
                        continue
                    if error.code is not None and error.code >= 500:
                        self._cooldown_until[model] = time.monotonic() + 60
                        continue
                    raise
                except httpx.HTTPError as error:
                    last = error
                    self._cooldown_until[model] = time.monotonic() + 30
                    logger.warning("groq_network_error model=%s error=%s", model, type(error).__name__)
                    continue
                choice = (data.get("choices") or [{}])[0]
                return choice.get("message") or {}, model
            upcoming = [t - time.monotonic() for m, t in self._cooldown_until.items() if m in chain]
            soonest = min((w for w in upcoming if w > 0), default=None)
            if soonest is None or soonest > MAX_POOL_WAIT:
                break
            logger.info("groq_pool_wait seconds=%.0f", soonest)
            await asyncio.sleep(soonest + 0.5)
        if last is not None:
            raise last
        raise GroqError("Denenecek Groq modeli yok", 404)

    # --- yapılandırılmış istek / arama ----------------------------------------

    async def generate_json(self, prompt: str, schema: dict) -> str:
        messages = [
            {"role": "system", "content": "Yalnızca geçerli bir JSON nesnesi döndür, başka metin yazma. "
                                          "Şu JSON şemasına uy: " + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))},
            {"role": "user", "content": prompt},
        ]
        message, _ = await self._chat(messages, json_mode=True, max_tokens=8000)
        return strip_thinking(str(message.get("content") or ""))

    async def search_text(self, prompt: str) -> tuple[str, list[str]]:
        from app.agent.gemini_backend import GeminiCapabilityError
        from app.agent.tavily import TavilyError, queries_for

        if self.tavily is None:
            raise GeminiCapabilityError("İnternet araması için TAVILY_API_KEY tanımlı değil")
        try:
            return await self.tavily.search(queries_for(prompt))
        except TavilyError as error:
            # 432/433: aylık kredi bitti; araştırma aramasız sürebilsin diye kota (429) sayılır.
            code = 429 if error.code in (429, 432, 433) else (403 if error.code in (401, 403) else error.code)
            raise GroqError(str(error), code) from error

    async def web_search(self, query: str) -> str:
        if not query.strip():
            return "Arama metni boş."
        if self.tavily is None:
            return "İnternet araması kapalı (Tavily anahtarı yok). Kendi bilginle devam et."
        try:
            text, sources = await self.tavily.search([query], max_results=3)
        except Exception as error:
            logger.exception("agent_web_search_failed")
            return f"Arama yapılamadı ({type(error).__name__}). Kullanıcıya söyle; mevcut menüyü koru."
        if not text:
            return "Aramadan kullanılabilir bir sonuç çıkmadı."
        return text[:6000] + ("\n\nKaynaklar:\n" + "\n".join(f"- {s}" for s in sources[:5]) if sources else "")

    # --- asistan döngüsü --------------------------------------------------------

    async def run_turn(self, system_text: str, tools: list, history: list[dict], message: str,
                       calls_log: list[str], images: list[tuple[str, bytes]] | None = None) -> tuple[str, str | None]:
        by_name = {tool.name: tool for tool in tools}
        specs = [{"type": "function", "function": {"name": t.name, "description": short_description(t.description),
                                                   "parameters": t.input_schema}} for t in tools]
        if self.settings.agent_web_search_enabled and self.tavily is not None:
            specs.append(WEB_SPEC)
        vision = bool(images) and bool(self.settings.groq_vision_model)
        user_content: str | list = message
        if images and not vision:
            # Groq'ta görüntü anlayan model yok: hata vermek yerine söyle, yazıyla yardım et.
            user_content = (message + "\n\n(Sistem notu: Kullanıcı fotoğraf ekledi ama şu an fotoğraf "
                            "okunamıyor. Bunu kısaca söyle; fotoğraftaki yemek adlarını yazarsa yardım edeceğini belirt.)")
        elif images:
            user_content = [{"type": "text", "text": message}] + [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}
                for mime, data in images
            ]
        messages: list[dict] = [{"role": "system", "content": system_text}]
        for turn in history[-HISTORY_TURNS:]:
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": str(turn["content"])[:HISTORY_CHARS]})
        messages.append({"role": "user", "content": user_content})
        searches = nudges = 0
        for step in range(1, max(1, self.settings.agent_max_iterations) + 1):
            self._shrink_old_tool_results(messages)
            reply, model = await self._chat(messages, tools=specs, vision=vision)
            logger.info("agent_model_request step=%s model=%s", step, model)
            calls = reply.get("tool_calls") or []
            content = strip_thinking(str(reply.get("content") or ""))
            if not calls:
                if not content and nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content": "(Sistem notu) Kullanıcıya görünen bir cevap yazmadın. "
                                                                "Yaptıklarını ve sonucu kısaca yaz."})
                    continue
                return content, None
            messages.append({"role": "assistant", "content": content or None, "tool_calls": calls})
            for call in calls:
                function = call.get("function") or {}
                name = function.get("name", "")
                try:
                    args = json.loads(function.get("arguments") or "{}") or {}
                except ValueError:
                    args = {}
                logger.info("agent_tool_call step=%s tool=%s", step, name)
                if name == WEB_TOOL_NAME:
                    calls_log.append(f"web_ara({args.get('sorgu', '')!r})")
                    if searches >= self.settings.agent_web_search_max_uses:
                        result = "Bu turdaki arama sınırına ulaşıldı; elindeki bilgiyle devam et."
                    else:
                        searches += 1
                        result = await self.web_search(str(args.get("sorgu", "")))
                elif name in by_name:
                    try:
                        result = await by_name[name].call(args)
                    except Exception as error:
                        logger.exception("agent_tool_failed tool=%s", name)
                        result = f"Araç hata verdi: {type(error).__name__}: {error}"
                else:
                    result = f"'{name}' adında bir araç yok."
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": str(result)[:TOOL_RESULT_CHARS]})
        logger.warning("agent_step_limit calls=%s", len(calls_log))
        messages.append({"role": "user", "content": "(Sistem notu) Adım sınırına ulaşıldı. Araç çağırmadan, şimdiye "
                                                    "kadar yaptıklarını ve kalan işi kullanıcıya kısaca yaz."})
        try:
            reply, _ = await self._chat(messages, vision=vision)
            text = strip_thinking(str(reply.get("content") or ""))
        except Exception:
            logger.exception("agent_step_limit_summary_failed")
            text = ""
        return text, (None if text else "adim_siniri")

    @staticmethod
    def _shrink_old_tool_results(messages: list[dict]) -> None:
        """Son iki araç sonucu dışındakileri kısaltır: her adımda tüm geçmiş yeniden gönderiliyor."""
        tool_indexes = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        for index in tool_indexes[:-2]:
            content = messages[index]["content"]
            if len(content) > OLD_TOOL_RESULT_CHARS:
                messages[index]["content"] = content[:OLD_TOOL_RESULT_CHARS] + " …(kısaltıldı)"

    # --- denetim ------------------------------------------------------------------

    async def ping(self) -> str:
        reply, _ = await self._chat([{"role": "user", "content": "Sadece 'tamam' yaz."}], max_tokens=200)
        return strip_thinking(str(reply.get("content") or ""))

    async def check_models(self) -> list[tuple[str, bool, str]]:
        results = []
        for model in [*self.models, *([self.settings.groq_vision_model] if self.settings.groq_vision_model else [])]:
            try:
                data = await self._post(model, {"messages": [{"role": "user", "content": "Sadece 'tamam' yaz."}],
                                                "max_completion_tokens": 200})
                answer = strip_thinking(str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""))
                results.append((model, True, f"cevap: {answer[:30]!r}"))
            except GroqError as error:
                labels = {404: "BULUNAMADI", 429: "SINIR DOLU", 413: "ISTEK BUYUK", 401: "ANAHTAR GECERSIZ"}
                results.append((model, False, labels.get(error.code, f"{error.code}: {error.message[:60]}")))
            except httpx.HTTPError as error:
                results.append((model, False, f"ag hatasi: {type(error).__name__}"))
        return results

    async def list_models(self) -> list[str]:
        """Bu anahtarla Groq'ta açık olan modellerin adları."""
        response = await self.http.get("https://api.groq.com/openai/v1/models",
                                       headers={"Authorization": f"Bearer {self.settings.groq_api_key}"})
        response.raise_for_status()
        return sorted(str(m.get("id")) for m in response.json().get("data") or [] if m.get("active", True))

    async def check_search(self) -> list[tuple[str, str, bool, str]]:
        if self.tavily is None:
            return [("tavily", "-", False, "TAVILY_API_KEY yok")]
        try:
            text, sources = await self.tavily.search(["mercimek çorbası tarifi"], max_results=2)
            return [("tavily", "-", bool(sources), f"{len(sources)} kaynak")]
        except Exception as error:
            return [("tavily", "-", False, f"{type(error).__name__}: {str(error)[:80]}")]
