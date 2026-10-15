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
    # Varsayilan: tek model. Yedek model zinciri kendi testlerinde aciliyor.
    gemini_settings = settings.model_copy(
        update={"agent_provider": "gemini", "gemini_api_key": "test", "gemini_fallback_models": [], **overrides}
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
        (503, "UNAVAILABLE", "overloaded", "aşırı yoğun"),
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
async def test_check_agent_lists_every_model_and_picks_the_first_working(settings, monkeypatch, capsys):
    from app.agent.gemini_backend import GeminiBackend
    from app.cli.__main__ import _check_agent

    async def table(self):
        return [
            ("gemini-3.8-flash", False, "MESGUL (asiri yuk)"),
            ("gemini-3.5-flash-lite", True, "cevap: 'tamam'"),
            ("gemini-2.5-flash-lite", False, "BULUNAMADI (model yok/kapatilmis)"),
        ]

    monkeypatch.setattr(GeminiBackend, "check_models", table)

    code = await _check_agent(settings.model_copy(update={"agent_provider": "gemini", "gemini_api_key": "k"}))

    out = capsys.readouterr().out
    assert code == 0
    assert "gemini-3.8-flash" in out and "MESGUL" in out
    assert "bot gemini-3.5-flash-lite ile cevap verecek" in out


@pytest.mark.asyncio
async def test_check_agent_fails_when_no_model_answers(settings, monkeypatch, capsys):
    from app.agent.gemini_backend import GeminiBackend
    from app.cli.__main__ import _check_agent

    async def table(self):
        return [("gemini-3.8-flash", False, "MESGUL (asiri yuk)")]

    monkeypatch.setattr(GeminiBackend, "check_models", table)

    code = await _check_agent(settings.model_copy(update={"agent_provider": "gemini", "gemini_api_key": "k"}))

    assert code == 1
    assert "hicbir model cevap vermedi" in capsys.readouterr().out

# --- sessiz bekleme olmasin -------------------------------------------------


@pytest.mark.asyncio
async def test_a_hung_turn_answers_after_the_timeout(db, settings, session_factory):
    """Asili kalan bir model istegi botu sonsuza dek sessiz birakmamali."""
    import asyncio

    class HangingClient(FakeGeminiClient):
        async def _generate(self, *, model, contents, config=None):
            await asyncio.sleep(3600)

    agent = make_agent(settings, session_factory, HangingClient([]), agent_turn_timeout_seconds=1)

    reply = await agent.reply(chat_id=1, message="menü oluştur")

    assert reply.ok is False
    assert "uzun sürdü" in reply.text
    assert "/menu" in reply.text


@pytest.mark.asyncio
async def test_turn_progress_is_logged_as_it_happens(db, settings, session_factory, caplog):
    """Terminal mesaj gelir gelmez hareket gostermeli, tur bitince degil."""
    import logging

    caplog.set_level(logging.INFO)
    client = FakeGeminiClient([call_response(("aday_tarifler", {})), text_response("Aday yok.")])
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=5, message="adaylar")

    events = [r.getMessage().split()[0] for r in caplog.records if r.name.startswith("app.agent")]
    assert events[0] == "agent_turn_started"
    assert events.count("agent_model_request") == 2
    assert "agent_tool_call" in events
    assert events.index("agent_tool_call") < events.index("agent_turn")


@pytest.mark.asyncio
async def test_request_timeout_is_set_in_milliseconds(settings, session_factory):
    agent = MealPlannerAgent(
        settings.model_copy(
            update={"agent_provider": "gemini", "gemini_api_key": "test", "agent_request_timeout_seconds": 45}
        ),
        session_factory,
    )
    try:
        assert agent.client._api_client._http_options.timeout == 45_000
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_typing_indicator_stays_on_for_the_whole_turn(settings):
    """Telegram gostergeyi 5 sn'de kaldiriyor; uzun turda yenilenmeli ve tur
    bitince durmali."""
    import asyncio

    from app.agent.runner import AgentReply
    from app.bot.handlers import TelegramHandlers

    actions: list[int] = []
    replies: list[str] = []

    class FakeBot:
        async def send_chat_action(self, chat_id, action):
            actions.append(chat_id)

    class SlowAgent:
        async def reply(self, chat_id, message):
            await asyncio.sleep(9)  # 4 sn araliklarla en az 3 gosterge
            return AgentReply(text="Menü hazır.")

    class FakeMessage:
        async def reply_text(self, text, **kwargs):
            replies.append(text)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=77), effective_user=SimpleNamespace(id=77), effective_message=FakeMessage()
    )
    handlers = TelegramHandlers(settings, FakeBot())
    handlers.agent = SlowAgent()

    await handlers._agent_turn(update, "menü oluştur")
    sent_during_turn = len(actions)
    await asyncio.sleep(5)

    assert sent_during_turn >= 3
    assert len(actions) == sent_during_turn  # tur bitince durdu
    assert replies == ["Menü hazır."]



# --- yedek model zinciri -------------------------------------------------


def overloaded():
    return errors.ServerError(
        503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "This model is currently experiencing high demand."}}
    )


def retired():
    return errors.ClientError(404, {"error": {"code": 404, "status": "NOT_FOUND", "message": "model not found"}})


def bad_key():
    return errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "API key not valid."}})


class ModelAwareClient(FakeGeminiClient):
    """Her model icin ayri cevap sirasi: {"model": [cevap veya hata, ...]}."""

    def __init__(self, script: dict[str, list]):
        super().__init__([])
        self.script = {model: list(items) for model, items in script.items()}

    async def _generate(self, *, model, contents, config=None):
        self.requests.append(
            {"model": model, "contents": list(contents) if isinstance(contents, list) else contents, "config": config}
        )
        item = self.script[model].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


CHAIN = {"gemini_model": "ana", "gemini_fallback_models": ["yedek1", "yedek2"]}


@pytest.mark.asyncio
async def test_an_overloaded_model_falls_back_to_the_next(db, settings, session_factory, caplog):
    """Gercek log: gemini-3.8-flash 503 'high demand' donuyordu."""
    import logging

    caplog.set_level(logging.WARNING)
    client = ModelAwareClient({"ana": [overloaded()], "yedek1": [text_response("Merhaba!")]})
    agent = make_agent(settings, session_factory, client, **CHAIN)

    reply = await agent.reply(chat_id=1, message="selam")

    assert reply.ok
    assert reply.text == "Merhaba!"
    assert [r["model"] for r in client.requests] == ["ana", "yedek1"]
    assert any("agent_model_fallback from=ana to=yedek1" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_fallback_is_sticky_for_the_rest_of_the_turn(db, settings, session_factory):
    """Yedege gecilen turda ana modele geri donulmez: onceki adimlarin
    thoughtSignature alanlari yedek modelin uretimi."""
    client = ModelAwareClient(
        {
            "ana": [overloaded()],
            "yedek1": [call_response(("aday_tarifler", {})), text_response("Aday yok.")],
        }
    )
    agent = make_agent(settings, session_factory, client, **CHAIN)

    await agent.reply(chat_id=1, message="adaylar")

    assert [r["model"] for r in client.requests] == ["ana", "yedek1", "yedek1"]


@pytest.mark.asyncio
async def test_retired_and_rate_limited_models_are_skipped(db, settings, session_factory):
    quota = errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}})
    client = ModelAwareClient({"ana": [quota], "yedek1": [retired()], "yedek2": [text_response("Tamam.")]})
    agent = make_agent(settings, session_factory, client, **CHAIN)

    reply = await agent.reply(chat_id=1, message="selam")

    assert reply.ok
    assert [r["model"] for r in client.requests] == ["ana", "yedek1", "yedek2"]


@pytest.mark.asyncio
async def test_a_bad_key_does_not_fall_back(db, settings, session_factory):
    """Anahtar hatasi tum modeller icin ayni; denemeye devam etmek bosuna."""
    client = ModelAwareClient({"ana": [bad_key()], "yedek1": [text_response("olmamali")]})
    agent = make_agent(settings, session_factory, client, **CHAIN)

    reply = await agent.reply(chat_id=1, message="selam")

    assert reply.ok is False
    assert "GEMINI_API_KEY" in reply.text
    assert [r["model"] for r in client.requests] == ["ana"]


@pytest.mark.asyncio
async def test_when_every_model_is_busy_the_user_is_told(db, settings, session_factory):
    client = ModelAwareClient({"ana": [overloaded()], "yedek1": [overloaded()], "yedek2": [overloaded()]})
    agent = make_agent(settings, session_factory, client, **CHAIN)

    reply = await agent.reply(chat_id=1, message="selam")

    assert reply.ok is False
    assert "aşırı yoğun" in reply.text
    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_web_search_falls_back_without_moving_the_main_turn(db, settings, session_factory):
    """Arama kendi imleciyle yedege gecer; ana tur o an mesgul olmayan ana
    modelde kalir."""
    client = ModelAwareClient(
        {
            "ana": [call_response((WEB_TOOL_NAME, {"sorgu": "x"})), overloaded(), text_response("Buldum.")],
            "yedek1": [text_response("bulunan tarif")],
        }
    )
    agent = make_agent(settings, session_factory, client, **CHAIN)

    reply = await agent.reply(chat_id=1, message="ara")

    assert reply.ok
    assert [r["model"] for r in client.requests] == ["ana", "ana", "yedek1", "ana"]
    sent_back = client.requests[-1]["contents"][-1].parts[0].function_response.response["result"]
    assert "bulunan tarif" in sent_back


def test_fallback_chain_is_deduplicated_and_ordered(settings):
    from app.agent.gemini_backend import GeminiBackend

    backend = GeminiBackend(
        settings.model_copy(update={"gemini_model": "a", "gemini_fallback_models": ["b", "a", "c", "b"]}),
        client=FakeGeminiClient([]),
    )

    assert backend.models == ["a", "b", "c"]


def test_fallback_models_parse_from_env_string(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "m1, m2 ,,m3")

    assert Settings(_env_file=None).gemini_fallback_models == ["m1", "m2", "m3"]


@pytest.mark.asyncio
async def test_check_models_reports_each_model(settings):
    from app.agent.gemini_backend import GeminiBackend

    backend = GeminiBackend(
        settings.model_copy(update=CHAIN),
        client=ModelAwareClient({"ana": [overloaded()], "yedek1": [text_response("tamam")], "yedek2": [retired()]}),
    )

    results = await backend.check_models()

    assert [(m, ok) for m, ok, _ in results] == [("ana", False), ("yedek1", True), ("yedek2", False)]
    assert "MESGUL" in results[0][2]
    assert "BULUNAMADI" in results[2][2]
