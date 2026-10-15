from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.agent.conversation import ConversationStore
from app.agent.runner import FALLBACK_REPLY, MealPlannerAgent
from app.db.models import Feedback, PreferenceType, SessionState
from app.memory.preferences import PreferenceService
from app.planner.dates import next_week_start
from app.planner.service import MealPlannerService

WEEK = next_week_start(timezone="Europe/Istanbul")


# --- sahte Claude istemcisi --------------------------------------------
#
# Gercek SDK'yi test etmiyoruz; dongu etrafindaki KENDI kodumuzu test
# ediyoruz: sistem istemi kurulumu, onbellek isareti, gecmis yonetimi, metin
# cikarma ve hata yolu. Sahte istemci senaryoda yazili arac cagrilarini
# GERCEK arac nesneleri uzerinde cagirir, sonra son mesaji dondurur.


@dataclass
class FakeBlock:
    type: str
    text: str = ""


@dataclass
class FakeMessage:
    content: list[FakeBlock]
    stop_reason: str = "end_turn"


class FakeRunner:
    def __init__(self, tools, script, reply_text, stop_reason="end_turn"):
        # Sunucu araclari (web_search gibi) ham dict olarak gelir ve
        # Anthropic tarafinda kosar; burada cagrilacak bir fonksiyon yok.
        self.tools = {tool.name: tool for tool in tools if not isinstance(tool, dict)}
        self.server_tools = [tool for tool in tools if isinstance(tool, dict)]
        self.script = script
        self.reply_text = reply_text
        self.stop_reason = stop_reason
        self.executed: list[tuple[str, dict]] = []
        self._pending_result = None

    async def __aiter__(self):
        for name, payload in self.script:
            tool = self.tools[name]
            result = await tool.call(payload)
            self.executed.append((name, payload))
            self._pending_result = {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": name, "content": str(result)}],
            }
            yield FakeMessage(content=[FakeBlock("tool_use")], stop_reason="tool_use")
        self._pending_result = None
        yield FakeMessage(content=[FakeBlock("text", self.reply_text)], stop_reason=self.stop_reason)

    async def generate_tool_call_response(self):
        """Gercek runner'da bu bir coroutine; arac kostuysa tool_result mesaji
        doner, kosmadiysa None."""
        result, self._pending_result = self._pending_result, None
        return result


class FakeMessages:
    def __init__(self, owner):
        self.owner = owner

    def tool_runner(self, **kwargs):
        # Cagri anindaki mesajlarin kopyasini sakla: runner bitince ajan
        # kendi listesini buyutuyor, kayit ondan etkilenmemeli.
        self.owner.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if self.owner.raises:
            raise RuntimeError("api down")
        stop_reason = self.owner.stop_reasons.pop(0) if self.owner.stop_reasons else "end_turn"
        runner = FakeRunner(kwargs["tools"], self.owner.script, self.owner.reply_text, stop_reason)
        self.owner.runners.append(runner)
        return runner


class FakeClient:
    """`client.beta.messages.tool_runner(...)` yuzeyini taklit eder."""

    def __init__(self, script=(), reply_text="Tamamdır.", raises=False, stop_reasons=()):
        self.script = list(script)
        self.reply_text = reply_text
        self.raises = raises
        # Sirayla her tool_runner cagrisinin son mesajinin stop_reason'i.
        self.stop_reasons = list(stop_reasons)
        self.calls: list[dict] = []
        self.runners: list[FakeRunner] = []
        self.beta = type("Beta", (), {})()
        self.beta.messages = FakeMessages(self)

    @property
    def last(self) -> dict:
        return self.calls[-1]


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


def make_agent(settings, session_factory, client):
    agent_settings = settings.model_copy(update={"anthropic_api_key": "test-key"})
    return MealPlannerAgent(
        agent_settings,
        session_factory,
        client=client,
        store=ConversationStore(max_turns=6),
    )


# --- dongu gercekten araci calistiriyor mu? ----------------------------


@pytest.mark.asyncio
async def test_agent_runs_a_multi_step_tool_sequence(db, settings, session_factory):
    """Eski `if` zincirinde imkansiz olan sey: tek mesajda birden fazla
    arac, sirayla."""
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    target = next(i for i in session.meal_plan.items if i.date == WEEK and i.recipe.category == "main")
    client = FakeClient(
        script=[
            ("plani_getir", {"hafta": "aktif"}),
            ("gecmis_getir", {"hafta_sayisi": 6}),
            ("tarif_ara", {"sorgu": "fasulye"}),
            (
                "ogun_degistir",
                {
                    "tarih": WEEK.isoformat(),
                    "yeni_tarif": "Kuru Fasulye",
                    "gerekce": "Haftada bir baklagil olsun diye.",
                    "ogun_slotu": target.meal_slot,
                },
            ),
        ],
        reply_text="Pazartesi'yi Kuru Fasulye yaptım, çünkü haftada bir baklagil istiyorsun.",
    )
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=42, message="Pazartesi'ye baklagil koy")

    assert reply.ok
    assert "Kuru Fasulye" in reply.text
    # Dort arac da gercekten calisti ve veritabanini degistirdi
    assert [name for name, _ in client.runners[0].executed] == [
        "plani_getir",
        "gecmis_getir",
        "tarif_ara",
        "ogun_degistir",
    ]
    assert len(reply.tool_calls) == 4
    assert target.recipe.name == "Kuru Fasulye"
    assert db.scalars(select(Feedback)).all()[0].admin_text == "Haftada bir baklagil olsun diye."


@pytest.mark.asyncio
async def test_agent_reply_is_plain_text_without_markdown_parse_mode(db, settings, session_factory):
    """Ajan cevabi serbest metin; Markdown kacisi gerekmedigi icin ozel
    karakterli tarif adlari mesaji dusurmez (TG-01)."""
    client = FakeClient(script=[], reply_text="Kabak_Mücver ve Tavuk *Şiş* ekledim.")
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=1, message="ne var")

    assert reply.text == "Kabak_Mücver ve Tavuk *Şiş* ekledim."


# --- sistem istemi ve onbellek -----------------------------------------


@pytest.mark.asyncio
async def test_stable_prompt_is_cached_and_volatile_context_is_separate(db, settings, session_factory):
    PreferenceService(db).add("Domuz eti asla", PreferenceType.HARD)
    PreferenceService(db).add("Hafta içi kısa tarifler", PreferenceType.SOFT)
    await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    client = FakeClient()
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=7, message="selam")

    system = client.last["system"]
    assert len(system) == 2
    # Sabit on-ek onbellege alinir, degisken baglam ALINMAZ
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in system[1]
    assert "araçları kullanarak" in system[0]["text"]
    # Degisken blok bugunu, plani ve tercihleri tasiyor
    volatile = system[1]["text"]
    assert "Bugün:" in volatile
    assert WEEK.isoformat() in volatile
    assert "Domuz eti asla" in volatile
    assert "Hafta içi kısa tarifler" in volatile


@pytest.mark.asyncio
async def test_request_uses_configured_model_and_effort(db, settings, session_factory):
    client = FakeClient()
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="selam")

    assert client.last["model"] == "claude-opus-5-5"
    assert client.last["output_config"] == {"effort": "medium"}
    assert client.last["max_iterations"] == settings.agent_max_iterations
    # Opus 5.5'te dusunme kapatilamaz; parametre hic gonderilmemeli
    assert "thinking" not in client.last
    # Zorunlu arac secimi 400 dondurur; auto (varsayilan) kalmali
    assert "tool_choice" not in client.last


@pytest.mark.asyncio
async def test_all_tools_are_offered_to_the_model(db, settings, session_factory):
    client = FakeClient()
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="selam")

    client_tools = {t.name for t in client.last["tools"] if not isinstance(t, dict)}
    assert client_tools == {
        "plani_getir",
        "tarif_ara",
        "tarif_detay",
        "ogun_degistir",
        "alisveris_listesi",
        "gecmis_getir",
        "tercih_kaydet",
        "tarif_ekle",
        "aday_tarifler",
        "tarif_onayla",
        "tarif_cikar",
        "plan_hazirla",
        "plan_kaydet",
    }


# --- konusma hafizasi ---------------------------------------------------


@pytest.mark.asyncio
async def test_history_lets_the_next_turn_resolve_references(db, settings, session_factory):
    """Eski yolda her mesaj bagimsiz yonlendiriliyordu; "onu degil digerini"
    demek imkansizdi."""
    client = FakeClient(reply_text="Mercimek çorbası ekledim.")
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=99, message="çorba ekle")
    await agent.reply(chat_id=99, message="yok onu değil, diğerini")

    second = client.calls[1]["messages"]
    assert second[0] == {"role": "user", "content": "çorba ekle"}
    assert second[1] == {"role": "assistant", "content": "Mercimek çorbası ekledim."}
    assert second[2] == {"role": "user", "content": "yok onu değil, diğerini"}


@pytest.mark.asyncio
async def test_history_is_isolated_per_chat(db, settings, session_factory):
    client = FakeClient()
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="birinci sohbet")
    await agent.reply(chat_id=2, message="ikinci sohbet")

    assert client.calls[1]["messages"] == [{"role": "user", "content": "ikinci sohbet"}]


@pytest.mark.asyncio
async def test_history_is_capped(db, settings, session_factory):
    client = FakeClient()
    agent = make_agent(settings, session_factory, client)

    for i in range(8):
        await agent.reply(chat_id=5, message=f"mesaj {i}")

    # max_turns=6 -> en fazla 6 gecmis turu + yeni kullanici mesaji
    assert len(client.last["messages"]) == 7
    assert client.last["messages"][0]["content"] != "mesaj 0"


# --- hata yollari -------------------------------------------------------


@pytest.mark.asyncio
async def test_api_failure_answers_instead_of_going_silent(db, settings, session_factory):
    """RUN-03: hicbir mesaj cevapsiz kalmamali."""
    client = FakeClient(raises=True)
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=3, message="menüyü göster")

    assert reply.ok is False
    assert reply.text == FALLBACK_REPLY
    assert "/menu" in reply.text
    # Basarisiz tur gecmise yazilmaz
    assert agent.store.history(3) == []


@pytest.mark.asyncio
async def test_empty_model_response_asks_for_clarification(db, settings, session_factory):
    client = FakeClient(reply_text="   ")
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=4, message="hmm")

    assert reply.ok is False
    assert "anlayamadım" in reply.text
    assert agent.store.history(4) == []


@pytest.mark.asyncio
async def test_tool_error_is_reported_not_swallowed(db, settings, session_factory):
    """Onaylanmis plani degistirme denemesi: arac hata metni dondurur, dongu
    devam eder, kullaniciya cevap gider."""
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(WEEK)
    planner.approve(session)
    session.state = SessionState.PUBLISHED
    db.commit()
    client = FakeClient(
        script=[("ogun_degistir", {"tarih": WEEK.isoformat(), "yeni_tarif": "Nohut", "gerekce": "x"})],
        reply_text="Bu hafta yayınlanmış, değiştiremiyorum. /regenerate ile yeni taslak çıkarabilirim.",
    )
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=8, message="pazartesi nohut yap")

    assert reply.ok
    assert "değiştiremiyorum" in reply.text


# --- etkinlestirme kosulu ----------------------------------------------


def test_agent_is_off_without_api_key(settings):
    assert MealPlannerAgent.available(settings) is False


def test_agent_is_on_with_api_key(settings):
    assert MealPlannerAgent.available(settings.model_copy(update={"anthropic_api_key": "k"})) is True


def test_agent_can_be_disabled_explicitly(settings):
    disabled = settings.model_copy(update={"anthropic_api_key": "k", "agent_enabled": False})

    assert MealPlannerAgent.available(disabled) is False


# --- web arama ve pause_turn -------------------------------------------


@pytest.mark.asyncio
async def test_web_search_server_tool_is_offered(db, settings, session_factory):
    client = FakeClient()
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="selam")

    server = [t for t in client.last["tools"] if isinstance(t, dict)]
    assert server == [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": settings.agent_web_search_max_uses}
    ]


@pytest.mark.asyncio
async def test_web_search_can_be_turned_off(db, settings, session_factory):
    off = settings.model_copy(update={"agent_web_search_enabled": False})
    client = FakeClient()
    agent = make_agent(off, session_factory, client)

    await agent.reply(chat_id=1, message="selam")

    assert [t for t in client.last["tools"] if isinstance(t, dict)] == []


@pytest.mark.asyncio
async def test_paused_turn_is_resumed_instead_of_truncating(db, settings, session_factory):
    """Python runner `pause_turn`da kendiliginden devam etmiyor; devam
    ettirmezsek cevap sessizce yarim kalir."""
    client = FakeClient(reply_text="Aramayı bitirdim.", stop_reasons=["pause_turn", "end_turn"])
    agent = make_agent(settings, session_factory, client)

    reply = await agent.reply(chat_id=1, message="yeni bir tarif bul")

    assert reply.ok
    assert reply.text == "Aramayı bitirdim."
    # Iki kez calistirildi: ilki duraklad, ikincisi tamamladi
    assert len(client.calls) == 2
    # Ikinci cagri duraklayan turu da tasiyor
    assert len(client.calls[1]["messages"]) > len(client.calls[0]["messages"])


@pytest.mark.asyncio
async def test_pause_restarts_are_capped(db, settings, session_factory):
    """Surekli duraklayan bir tur sonsuz donguye girmemeli."""
    capped = settings.model_copy(update={"agent_max_pause_restarts": 2})
    client = FakeClient(reply_text="yarım", stop_reasons=["pause_turn"] * 10)
    agent = make_agent(capped, session_factory, client)

    reply = await agent.reply(chat_id=1, message="ara")

    assert len(client.calls) == 3  # ilk cagri + 2 yeniden baslatma
    assert reply.text == "yarım"


@pytest.mark.asyncio
async def test_tool_results_are_mirrored_for_resume(db, settings, session_factory):
    """Duraklamadan sonra devam edebilmek icin arac sonuclari gecmise
    yansitilmali, yoksa model ne yaptigini unutur."""
    client = FakeClient(
        script=[("aday_tarifler", {})],
        reply_text="Aday yok.",
        stop_reasons=["pause_turn", "end_turn"],
    )
    agent = make_agent(settings, session_factory, client)

    await agent.reply(chat_id=1, message="adaylar ne durumda")

    resumed = client.calls[1]["messages"]
    assert any(
        isinstance(m.get("content"), list)
        and any(b.get("type") == "tool_result" for b in m["content"] if isinstance(b, dict))
        for m in resumed
    )
