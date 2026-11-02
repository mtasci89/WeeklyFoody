"""Groq + Tavily (Google'sız) arka uç: ağa çıkmadan, sahte HTTP cevaplarıyla."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

import app.agent.groq_backend as groq_module
from app.agent.ai import make_backend, uses_groq
from app.agent.groq_backend import GroqBackend, GroqError
from app.agent.tavily import TavilySearch, queries_for
from test_agent_gemini import session_factory  # noqa: F401


def groq_settings(settings, **update):
    return settings.model_copy(update={
        "agent_provider": "groq", "google_enabled": False, "groq_api_key": "g" * 20, "tavily_api_key": "t" * 20,
        "groq_models": ["model-a", "model-b"], **update,
    })


class FakeGroq:
    """Sırayla verilen cevapları dönen /chat/completions."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        reply = self.replies.pop(0)
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json={"choices": [{"message": reply}]})


def limited(seconds=5):
    return httpx.Response(429, headers={"retry-after": str(seconds)},
                          json={"error": {"message": f"Rate limit reached. Please try again in {seconds}s", "code": "rate_limit_exceeded"}})


def backend(settings, replies, tavily=None):
    fake = FakeGroq(replies)
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return GroqBackend(groq_settings(settings), http=http, tavily=tavily), fake


@pytest.fixture()
def no_sleep(monkeypatch):
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(groq_module.asyncio, "sleep", fake_sleep)
    return waits


def test_without_google_the_backend_is_groq(settings):
    configured = groq_settings(settings, agent_provider="gemini")  # eski .env'de gemini yazsa bile
    assert uses_groq(configured)
    assert isinstance(make_backend(configured), GroqBackend)


@pytest.mark.asyncio
async def test_a_tool_step_then_an_answer(settings):
    calls = []

    async def run(args):
        calls.append(args)
        return "Salı: Izgara Köfte"

    tool = SimpleNamespace(name="plani_getir", description="Planı getirir.\n\nUzun açıklama.", input_schema={"type": "object", "properties": {}}, call=run)
    sdk, fake = backend(settings, [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "plani_getir", "arguments": "{}"}}]},
        {"role": "assistant", "content": "Salı'da Izgara Köfte var."},
    ])
    log: list[str] = []

    text, problem = await sdk.run_turn("sistem", [tool], [], "Salı ne var?", log)

    assert text == "Salı'da Izgara Köfte var." and problem is None and calls == [{}]
    second = fake.bodies[1]["messages"]
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": "Salı: Izgara Köfte"}
    # Kısa araç açıklaması: yalnız ilk paragraf.
    assert fake.bodies[0]["tools"][0]["function"]["description"] == "Planı getirir."


@pytest.mark.asyncio
async def test_rate_limited_model_hands_over_to_the_next(settings):
    sdk, fake = backend(settings, [limited(20), {"role": "assistant", "content": "tamam"}])
    assert await sdk.ping() == "tamam"
    assert [b["model"] for b in fake.bodies] == ["model-a", "model-b"]
    assert sdk._cooldown_until["model-a"] > 0


@pytest.mark.asyncio
async def test_when_every_model_is_limited_it_waits_for_the_soonest(settings, no_sleep):
    sdk, fake = backend(settings, [limited(5), limited(9), {"role": "assistant", "content": "tamam"}])
    sdk._cooldown_until.clear()
    # Bekleme sahte: süre dolmuş sayılsın diye monotonic'i ilerlet.
    original = groq_module.time.monotonic
    shift = {"s": 0.0}
    groq_module.time.monotonic = lambda: original() + shift["s"]

    async def advance(seconds):
        no_sleep.append(seconds)
        shift["s"] += seconds

    groq_module.asyncio.sleep = advance
    try:
        assert await sdk.ping() == "tamam"
    finally:
        groq_module.time.monotonic = original
    assert no_sleep and 5 <= no_sleep[0] <= 6
    assert [b["model"] for b in fake.bodies] == ["model-a", "model-b", "model-a"]


@pytest.mark.asyncio
async def test_json_requests_ask_for_a_json_object(settings):
    sdk, fake = backend(settings, [{"role": "assistant", "content": '{"tarifler": []}'}])
    assert await sdk.generate_json("yapılandır", {"type": "object"}) == '{"tarifler": []}'
    assert fake.bodies[0]["response_format"] == {"type": "json_object"}


def test_three_main_dishes_need_one_search_query():
    prompt = ("HEDEFLER:\n1) 2026-11-02: dinner_main, rol=main; tabak: x\n2) 2026-11-03: dinner_main, rol=main; tabak: y\n"
              "3) 2026-11-04: dinner_main, rol=main; tabak: z\nİSTEK:\ndaha hafif olsun\nEV KURALLARI:\n- kabak yok")
    queries = queries_for(prompt)
    assert len(queries) == 1 and "ana yemek" in queries[0] and "daha hafif olsun" in queries[0]


@pytest.mark.asyncio
async def test_tavily_pages_become_search_text_and_sources(settings):
    queries = []

    def handler(request):
        assert request.headers["authorization"] == "Bearer " + "t" * 20
        queries.append(json.loads(request.content)["query"])
        menu_junk = "Ana sayfa | Tarifler | Giriş " * 20
        return httpx.Response(200, json={"results": [
            {"title": "Fırında Hünkar", "url": "https://tarif.example/hunkar",
             "raw_content": menu_junk + "Malzemeler: 500 g kuzu, 2 patlıcan. Hazırlanışı: kuzuyu pişirin."},
            {"title": "Kopya", "url": "https://tarif.example/hunkar", "content": "aynı sayfa"},
        ]})

    tavily = TavilySearch("t" * 20, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    # Önce Groq somut yemek adını önerir, sonra tam o yemeğin tarifi aranır.
    sdk, _ = backend(settings, [{"role": "assistant", "content": '{"hedefler": [{"icin": 1, "ad": "Fırında Hünkar"}]}'}],
                     tavily=tavily)

    text, sources = await sdk.search_text("HEDEFLER:\n1) 2026-11-02: dinner_main, rol=main; tabak: x")

    assert queries == ["Fırında Hünkar tarifi malzemeler"]
    assert "500 g kuzu" in text and text.count("Ana sayfa") < 8  # sayfa başındaki menü atıldı
    assert sources == ["Fırında Hünkar: https://tarif.example/hunkar"]


@pytest.mark.asyncio
async def test_tavily_out_of_credits_counts_as_quota_so_research_goes_offline(settings):
    from app.planner.research import search_unavailable

    tavily = TavilySearch("t" * 20, client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(432, json={}))))
    sdk, _ = backend(settings, [], tavily=tavily)
    with pytest.raises(GroqError) as caught:
        await sdk.search_text("bir şey ara")
    assert caught.value.code == 429 and search_unavailable(caught.value)


@pytest.mark.asyncio
async def test_agent_runs_on_groq_with_the_short_prompt(settings, session_factory, monkeypatch):
    from app.agent.prompts import GROQ_SYSTEM_PROMPT, SYSTEM_PROMPT
    from app.agent.runner import MealPlannerAgent

    seen = {}

    async def fake_turn(self, system_text, tools, history, message, calls_log, images=None):
        seen["system"] = system_text
        return "Merhaba", None

    monkeypatch.setattr(GroqBackend, "run_turn", fake_turn)
    agent = MealPlannerAgent(groq_settings(settings), session_factory)

    reply = await agent.reply(1, "selam", channel="uygulama")

    assert reply.text.startswith("Merhaba") and agent.provider == "groq"
    assert seen["system"].startswith(GROQ_SYSTEM_PROMPT) and len(GROQ_SYSTEM_PROMPT) < len(SYSTEM_PROMPT) / 3


@pytest.mark.asyncio
async def test_photos_without_a_vision_model_are_explained_not_failed(settings):
    sdk, fake = backend(settings, [{"role": "assistant", "content": "Fotoğrafı okuyamıyorum; adlarını yazar mısın?"}])
    sdk.settings = sdk.settings.model_copy(update={"groq_vision_model": ""})

    text, problem = await sdk.run_turn("sistem", [], [], "bunları ekle", [], images=[("image/jpeg", b"x")])

    assert problem is None and "okuyamıyorum" in text
    sent = fake.bodies[0]["messages"][-1]["content"]
    assert isinstance(sent, str) and "fotoğraf" in sent and fake.bodies[0]["model"] == "model-a"


def test_requests_fit_the_per_minute_token_budget(settings):
    from app.agent.groq_backend import TPM_BUDGET, compact_schema, estimate_tokens, pick_tools, short_description
    from app.agent.prompts import GROQ_SYSTEM_PROMPT
    from app.agent.tools import MealAgentToolset

    tools = MealAgentToolset(settings, lambda: None).build()
    chosen = pick_tools(tools, "Çarşamba yemeğini değiştir", [])
    names = {t.name for t in chosen}
    assert "yenisiyle_degistir" in names and "alisveris_listesi" not in names and "kiler" not in names
    assert "alisveris_listesi" in {t.name for t in pick_tools(tools, "alışveriş listesini göster", [])}
    specs = [{"type": "function", "function": {"name": t.name, "description": short_description(t.description),
                                               "parameters": compact_schema(t.input_schema)}} for t in chosen]
    assert all("title" not in json.dumps(s["function"]["parameters"]) for s in specs)
    body = {"messages": [{"role": "system", "content": GROQ_SYSTEM_PROMPT + "x" * 1500}], "tools": specs}
    assert estimate_tokens(body) < TPM_BUDGET / 2  # cevaba yer kalsın


@pytest.mark.asyncio
async def test_completion_room_is_capped_and_gpt_oss_thinks_briefly(settings):
    sdk, fake = backend(settings, [{"role": "assistant", "content": "tamam"}])
    sdk.settings = sdk.settings.model_copy(update={"groq_models": ["openai/gpt-oss-120b"]})
    await sdk._chat([{"role": "user", "content": "x" * 15000}])
    body = fake.bodies[0]
    assert body["max_completion_tokens"] <= 7600 - 5000 and body["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_a_too_large_request_is_shrunk_and_retried(settings):
    too_large = httpx.Response(413, json={"error": {"message": "Request too large for model", "code": "rate_limit_exceeded"}})
    sdk, fake = backend(settings, [too_large, too_large, {"role": "assistant", "content": "oldu"}])
    history = [{"role": "user", "content": "eski " * 100}, {"role": "assistant", "content": "cevap " * 100}]

    text, problem = await sdk.run_turn("sistem", [], history, "yeni mesaj", [])

    assert text == "oldu"
    last = fake.bodies[-1]["messages"]
    assert [m["role"] for m in last] == ["system", "user"] and last[-1]["content"] == "yeni mesaj"
