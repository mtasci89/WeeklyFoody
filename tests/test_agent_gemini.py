from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors, types
from sqlalchemy import select

from app.agent.conversation import ConversationStore
from app.agent.gemini_backend import WEB_TOOL_NAME
from app.agent.runner import MealPlannerAgent
from app.db.models import Feedback
from app.planner.dates import next_week_start
from app.planner.service import MealPlannerService

WEEK = next_week_start(timezone="Europe/Istanbul")


# --- sahte Gemini istemcisi --------------------------------------------
#
# Cevaplar SDK'nin GERCEK pydantic tipleriyle kuruluyor; kod, canli API'nin
# dondurdugu yapinin aynisiyla sinaniyor. Yalnizca ag cagrisi taklit.


def call_response(*calls: tuple[str, dict], signature: bytes = b"imza") -> types.GenerateContentResponse:
    # Paralel cagrilarda imzayi yalnizca ilk parca tasir (Gemini 3 davranisi).
    parts = [
        types.Part(
            function_call=types.FunctionCall(id=f"c{i}", name=name, args=args),
            thought_signature=signature if i == 0 else None,
        )
        for i, (name, args) in enumerate(calls)
    ]
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts), finish_reason="STOP")]
    )


def text_response(text: str, thought: str | None = None, sources=()) -> types.GenerateContentResponse:
    parts = []
    if thought:
        parts.append(types.Part(text=thought, thought=True))
    parts.append(types.Part(text=text))
    metadata = None
    if sources:
        metadata = types.GroundingMetadata(
            grounding_chunks=[
                types.GroundingChunk(web=types.GroundingChunkWeb(uri=uri, title=title)) for title, uri in sources
            ]
        )
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=parts),
                finish_reason="STOP",
                grounding_metadata=metadata,
            )
        ]
    )


class FakeGeminiClient:
    """`client.aio.models.generate_content(...)` yuzeyini taklit eder."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model, contents, config=None):
        # Cagri anindaki kopya: dongu `contents`i sonradan buyutuyor.
        self.requests.append(
            {"model": model, "contents": list(contents) if isinstance(contents, list) else contents, "config": config}
        )
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def session_factory(db):
    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    return _Factory()


def make_agent(settings, session_factory, client, **overrides):
    gemini_settings = settings.model_copy(
        update={"agent_provider": "gemini", "gemini_api_key": "test", **overrides}
    )
    return MealPlannerAgent(gemini_settings, session_factory, client=client, store=ConversationStore(max_turns=6))


def declarations(request) -> dict:
    return {d.name: d for d in request["config"].tools[0].function_declarations}


# --- dongu ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_runs_a_multi_step_tool_sequence(db, settings, session_factory):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    target = next(i for i in session.meal_plan.items if i.date == WEEK and i.recipe.category == "main")
    client = FakeGeminiClient(
        [
            call_response(("plani_getir", {"hafta": "aktif"})),
            call_response(("tarif_ara", {"sorgu": "fasulye"})),
            call_response(
                (
                    "ogun_degistir",
                    {
                        "tarih": WEEK.isoformat(),
                        "yeni_tarif": "Kuru Fasulye",
                        "gerekce": "Haftada bir baklagil olsun.",
                        "ogun_slotu": target.meal_slot,
                    },
                )
            ),
            text_response("Pazartesi'yi Kuru Fasulye yaptım, haftada bir baklagil istediğin için."),
        ]
    )
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=42, message="Pazartesi'ye baklagil koy")

    assert reply.ok
    assert "Kuru Fasulye" in reply.text
    assert len(client.requests) == 4
    assert [c.split("(")[0] for c in reply.tool_calls] == ["plani_getir", "tarif_ara", "ogun_degistir"]
    assert target.recipe.name == "Kuru Fasulye"
    assert db.scalars(select(Feedback)).all()[0].admin_text == "Haftada bir baklagil olsun."


@pytest.mark.asyncio
async def test_function_results_go_back_with_matching_id_and_name(db, settings, session_factory):
    client = FakeGeminiClient([call_response(("aday_tarifler", {})), text_response("Aday yok.")])
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="adaylar")

    last_turn = client.requests[1]["contents"][-1]
    assert last_turn.role == "user"
    response = last_turn.parts[0].function_response
    assert (response.id, response.name) == ("c0", "aday_tarifler")
    assert "aday tarif yok" in response.response["result"]


@pytest.mark.asyncio
async def test_thought_signature_is_sent_back_unchanged(db, settings, session_factory):
    """Gemini 3 imzasiz gonderilen fonksiyon cagrisi turunu 400 ile reddediyor."""
    client = FakeGeminiClient([call_response(("aday_tarifler", {}), signature=b"gizli-imza"), text_response("Tamam.")])
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="adaylar")

    model_turn = client.requests[1]["contents"][-2]
    assert model_turn.role == "model"
    assert model_turn.parts[0].thought_signature == b"gizli-imza"


@pytest.mark.asyncio
async def test_parallel_calls_are_answered_in_one_user_turn(db, settings, session_factory):
    client = FakeGeminiClient(
        [
            call_response(("aday_tarifler", {}), ("gecmis_getir", {"hafta_sayisi": 4})),
            text_response("İkisine de baktım."),
        ]
    )
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="adaylar ve geçmiş")

    last_turn = client.requests[1]["contents"][-1]
    assert [p.function_response.name for p in last_turn.parts] == ["aday_tarifler", "gecmis_getir"]


@pytest.mark.asyncio
async def test_thinking_text_is_not_shown_to_the_user(db, settings, session_factory):
    client = FakeGeminiClient([text_response("Merhaba!", thought="Kullanıcı selam verdi, kısa cevap ver.")])
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=1, message="selam")

    assert reply.text == "Merhaba!"


@pytest.mark.asyncio
async def test_history_is_converted_to_gemini_roles(db, settings, session_factory):
    client = FakeGeminiClient([text_response("Mercimek çorbası ekledim."), text_response("Tamam, diğeri.")])
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=9, message="çorba ekle")
    await agent.reply(chat_id=9, message="yok onu değil")

    contents = client.requests[1]["contents"]
    assert [(c.role, c.parts[0].text) for c in contents] == [
        ("user", "çorba ekle"),
        ("model", "Mercimek çorbası ekledim."),
        ("user", "yok onu değil"),
    ]


# --- istek kurulumu -------------------------------------------------------


@pytest.mark.asyncio
async def test_request_declares_every_tool_with_its_json_schema(db, settings, session_factory):
    client = FakeGeminiClient([text_response("selam")])
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="selam")

    request = client.requests[0]
    decls = declarations(request)
    assert set(decls) == {
        "plan_hazirla", "plan_kaydet", "plani_getir", "tarif_ara", "tarif_detay", "ogun_degistir",
        "alisveris_listesi", "gecmis_getir", "tercih_kaydet", "tarif_ekle", "aday_tarifler",
        "tarif_onayla", "tarif_cikar", WEB_TOOL_NAME,
    }
    # Araclarin urettigi JSON Schema oldugu gibi gidiyor
    from app.agent.tools import MealAgentToolset

    plan_kaydet = next(t for t in MealAgentToolset(settings, session_factory).build() if t.name == "plan_kaydet")
    assert decls["plan_kaydet"].parameters_json_schema == plan_kaydet.input_schema
    assert decls["plan_kaydet"].parameters is None
    # Donguyu biz yonetiyoruz
    assert request["config"].automatic_function_calling.disable is True
    assert request["model"] == settings.gemini_model


@pytest.mark.asyncio
async def test_system_instruction_names_the_gemini_search_tool(db, settings, session_factory):
    await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    client = FakeGeminiClient([text_response("selam")])
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="selam")

    system = client.requests[0]["config"].system_instruction
    assert "`web_ara`" in system
    assert "`web_search`" not in system
    assert "Bugün:" in system
    assert WEEK.isoformat() in system


@pytest.mark.asyncio
async def test_web_search_can_be_turned_off(db, settings, session_factory):
    client = FakeGeminiClient([text_response("selam")])
    agent = make_agent(settings, session_factory, client, agent_web_search_enabled=False)

    await agent.reply(chat_id=1, message="selam")

    assert WEB_TOOL_NAME not in declarations(client.requests[0])


# --- web araması ----------------------------------------------------------


@pytest.mark.asyncio
async def test_web_search_runs_a_grounded_request_and_returns_sources(db, settings, session_factory):
    client = FakeGeminiClient(
        [
            call_response((WEB_TOOL_NAME, {"sorgu": "kore usulü tavuk"})),
            text_response(
                "Dakgalbi: 600 gr tavuk, 2 yemek kaşığı gochujang...",
                sources=[("Örnek Mutfak", "https://ornek.com/dakgalbi")],
            ),
            text_response("Dakgalbi buldum, aday olarak ekleyeyim mi?"),
        ]
    )
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=1, message="kore usulü tavuk bul")

    grounded = client.requests[1]
    assert grounded["config"].tools[0].google_search is not None
    assert not grounded["config"].tools[0].function_declarations
    sent_back = client.requests[2]["contents"][-1].parts[0].function_response
    assert sent_back.name == WEB_TOOL_NAME
    assert "gochujang" in sent_back.response["result"]
    assert "https://ornek.com/dakgalbi" in sent_back.response["result"]
    assert reply.tool_calls == ["web_ara('kore usulü tavuk')"]


@pytest.mark.asyncio
async def test_web_search_limit_is_enforced(db, settings, session_factory):
    client = FakeGeminiClient(
        [
            call_response((WEB_TOOL_NAME, {"sorgu": "bir"})),
            text_response("sonuç bir"),
            call_response((WEB_TOOL_NAME, {"sorgu": "iki"})),
            text_response("Tamam."),
        ]
    )
    agent = make_agent(settings, session_factory, client, agent_web_search_max_uses=1)

    await agent.reply(chat_id=1, message="ara")

    # Ikinci arama icin grounded istek ATILMADI: 4 istek, 5 degil
    assert len(client.requests) == 4
    refused = client.requests[3]["contents"][-1].parts[0].function_response.response["result"]
    assert "sınırına ulaşıldı" in refused


@pytest.mark.asyncio
async def test_failed_web_search_is_reported_to_the_model(db, settings, session_factory):
    quota = errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    client = FakeGeminiClient(
        [call_response((WEB_TOOL_NAME, {"sorgu": "x"})), quota, text_response("Arayamadım, kütüphaneden devam.")]
    )
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=1, message="ara")

    assert reply.ok
    assert "Arama yapılamadı" in client.requests[2]["contents"][-1].parts[0].function_response.response["result"]


# --- hata yollari --------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_exception_becomes_an_error_result_not_a_crash(db, settings, session_factory):
    client = FakeGeminiClient([call_response(("tarif_detay", {})), text_response("Adı eksikti.")])
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=1, message="tarif")

    assert reply.ok
    assert "Araç hata verdi" in client.requests[1]["contents"][-1].parts[0].function_response.response["result"]


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_to_the_model(db, settings, session_factory):
    client = FakeGeminiClient([call_response(("olmayan_arac", {})), text_response("Tamam.")])
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="x")

    assert "adında bir araç yok" in client.requests[1]["contents"][-1].parts[0].function_response.response["result"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "status", "message", "expected"),
    [
        (429, "RESOURCE_EXHAUSTED", "Resource has been exhausted", "ücretsiz kotası doldu"),
        (400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.", "GEMINI_API_KEY"),
        (404, "NOT_FOUND", "models/gemini-9 is not found", "GEMINI_MODEL geçerli"),
        (503, "UNAVAILABLE", "overloaded", "geçici"),
    ],
)
async def test_api_errors_explain_themselves(db, settings, session_factory, code, status, message, expected):
    error_cls = errors.ServerError if code >= 500 else errors.ClientError
    error = error_cls(code, {"error": {"code": code, "message": message, "status": status}})
    agent = make_agent(settings, session_factory, FakeGeminiClient([error]))

    reply = await agent.reply(chat_id=1, message="selam")

    assert reply.ok is False
    assert expected in reply.text
    assert "/menu" in reply.text
    assert agent.store.history(1) == []


@pytest.mark.asyncio
async def test_empty_candidate_asks_for_clarification(db, settings, session_factory):
    agent = make_agent(settings, session_factory, FakeGeminiClient([types.GenerateContentResponse(candidates=[])]))

    reply = await agent.reply(chat_id=1, message="selam")

    assert reply.ok is False
    assert "anlayamadım" in reply.text


@pytest.mark.asyncio
async def test_endless_tool_calls_stop_at_the_iteration_limit(db, settings, session_factory):
    loop = [call_response(("aday_tarifler", {})) for _ in range(5)]
    agent = make_agent(settings, session_factory, FakeGeminiClient(loop), agent_max_iterations=3)

    reply = await agent.reply(chat_id=1, message="x")

    assert reply.ok is False
    assert len(agent.client.requests) == 3


# --- kurulum ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_client_is_built_with_quota_retries(settings, session_factory):
    """Ag cagrisi olmadan kurulabilmeli; 429'da tekrar denemeli."""
    agent = MealPlannerAgent(
        settings.model_copy(update={"agent_provider": "gemini", "gemini_api_key": "test"}), session_factory
    )
    try:
        retry = agent.client._api_client._http_options.retry_options
        assert 429 in retry.http_status_codes
        assert retry.attempts >= 2
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_ping_reports_the_model_answer(db, settings, session_factory):
    agent = make_agent(settings, session_factory, FakeGeminiClient([text_response("tamam")]))

    assert await agent.ping() == "tamam"


@pytest.mark.asyncio
async def test_check_agent_reports_a_missing_key(settings, capsys):
    from app.cli.__main__ import _check_agent

    code = await _check_agent(settings.model_copy(update={"agent_provider": "gemini", "gemini_api_key": ""}))

    assert code == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_check_agent_explains_a_failure(settings, monkeypatch, capsys):
    from app.cli.__main__ import _check_agent

    async def quota(self):
        raise errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    monkeypatch.setattr(MealPlannerAgent, "ping", quota)

    code = await _check_agent(settings.model_copy(update={"agent_provider": "gemini", "gemini_api_key": "k"}))

    out = capsys.readouterr().out
    assert code == 1
    assert "ücretsiz kotası doldu" in out
    assert "Model     : gemini" in out


@pytest.mark.asyncio
async def test_check_agent_reports_success(settings, monkeypatch, capsys):
    from app.cli.__main__ import _check_agent

    async def ok(self):
        return "tamam"

    monkeypatch.setattr(MealPlannerAgent, "ping", ok)

    code = await _check_agent(settings.model_copy(update={"agent_provider": "gemini", "gemini_api_key": "k"}))

    assert code == 0
    assert "CALISIYOR" in capsys.readouterr().out


def test_retired_model_error_points_at_googles_suggestion_not_the_failing_model():
    """Gercek hata: gemini-2.5-flash yeni kullanicilara kapatildi. Eski ipucu
    tam da bu modeli oneriyordu ve Google'in onerisini 80 karakterde kesiyordu."""
    from app.agent.runner import explain_failure

    real = errors.ClientError(
        404,
        {
            "error": {
                "code": 404,
                "status": "NOT_FOUND",
                "message": (
                    "This model models/gemini-2.5-flash is no longer available to new users. "
                    "Please update your code to use models/gemini-3.8-flash for the latest "
                    "features and improvements."
                ),
            }
        },
    )

    text = explain_failure(real)

    assert "GEMINI_MODEL=gemini-3.8-flash" in text
    assert "gemini-2.5-flash" not in text


def test_default_model_is_not_the_retired_one(settings):
    assert settings.gemini_model != "gemini-2.5-flash"
