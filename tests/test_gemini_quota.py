"""Gemini kota hataları (429) ve model sırası.

Kullanıcı internetten yeni yemek isterken "Gemini/Google arama kotası aşıldı (429)"
aldı; Cal Track'te gemini-2.5-flash sorunsuz çalışıyor. Model seçimini kullanıcıya
bırakmıyoruz: arama önce 2.5-flash ile denenir, dakikalık sınırda beklenir, günlük
sınırda model saatlerce atlanır ve hata mesajı hangisi olduğunu söyler.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from google.genai import errors

import app.agent.gemini_backend as backend_module
from app.agent.gemini_backend import GeminiBackend, quota_scope, quota_wait_seconds
from app.planner.research import research_failure
from test_agent_gemini import FakeGeminiClient, text_response


def quota_error(per: str, retry: str | None = "12s"):
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": f"GenerateRequestsPer{per}PerProjectPerModel-FreeTier"}]}]
    if retry:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry})
    return errors.ClientError(429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED", "message": "You exceeded your current quota.", "details": details,
    }})


def make(settings, responses, **update):
    config = settings.model_copy(update={
        "gemini_model": "gemini-3.8-flash", "gemini_backup_model": "gemini-2.5-flash",
        "gemini_fallback_models": ["gemini-3.5-flash-lite"], "gemini_search_models": ["gemini-2.5-flash"], **update,
    })
    client = FakeGeminiClient(responses)
    return GeminiBackend(config, client), client


@pytest.fixture()
def no_sleep(monkeypatch):
    waits: list[float] = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(backend_module.asyncio, "sleep", fake_sleep)
    return waits


def test_quota_errors_are_classified():
    assert quota_scope(quota_error("Day")) == "günlük"
    assert quota_scope(quota_error("Minute")) == "dakikalık"
    assert quota_wait_seconds(quota_error("Minute", "12s")) == 13
    assert quota_wait_seconds(quota_error("Minute", "300s")) is None  # çok uzun: yedeğe geç
    assert quota_wait_seconds(quota_error("Day", "12s")) is None  # günlük: beklemek boşuna


def test_chat_chain_tries_25_flash_right_after_the_main_model(settings):
    sdk, _ = make(settings, [])
    assert sdk.models == ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite"]


@pytest.mark.asyncio
async def test_google_search_starts_with_25_flash(settings):
    sdk, client = make(settings, [text_response("Tarif", sources=[("Site", "https://ornek.com/t")])])
    text, sources = await sdk.search_text("ara")
    assert text == "Tarif" and client.requests[0]["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_minute_limit_waits_and_retries_the_same_model(settings, no_sleep):
    sdk, client = make(settings, [quota_error("Minute", "12s"), text_response("Tarif", sources=[("S", "https://a.com/b")])])
    await sdk.search_text("ara")
    assert [r["model"] for r in client.requests] == ["gemini-2.5-flash", "gemini-2.5-flash"]
    assert no_sleep == [13]


@pytest.mark.asyncio
async def test_daily_limit_moves_on_and_skips_the_model_for_hours(settings, no_sleep):
    sdk, client = make(settings, [
        quota_error("Day"), text_response("Tarif", sources=[("S", "https://a.com/b")]),
        text_response("İkinci", sources=[("S", "https://a.com/c")]),
    ])
    await sdk.search_text("ara")
    await sdk.search_text("tekrar")
    assert [r["model"] for r in client.requests] == ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.8-flash"]
    assert no_sleep == []
    assert sdk._cooldown_until["gemini-2.5-flash"] - backend_module.time.monotonic() > 2 * 3600


@pytest.mark.asyncio
async def test_a_closed_25_flash_is_skipped_automatically(settings):
    closed = errors.ClientError(404, {"error": {"code": 404, "status": "NOT_FOUND", "message": "model not found"}})
    sdk, client = make(settings, [closed, text_response("Tarif", sources=[("S", "https://a.com/b")])])
    await sdk.search_text("ara")
    assert [r["model"] for r in client.requests] == ["gemini-2.5-flash", "gemini-3.8-flash"]


@pytest.mark.asyncio
async def test_when_every_model_is_out_the_message_says_which_limit(settings, no_sleep):
    sdk, _ = make(settings, [quota_error("Day")] * 3)
    with pytest.raises(errors.ClientError) as caught:
        await sdk.search_text("ara")
    message = research_failure(caught.value, "Google araması")
    assert "günlük" in message and "yarın" in message and "gemini-3.5-flash-lite" in message

    minute = research_failure(quota_error("Minute"), "Google araması")
    assert "dakikalık" in minute and "dakika sonra" in minute


# --- Google araması kotada: aramasız öneri ---------------------------------------------

from test_menu_research import FakeWeb, configured  # noqa: E402

from app.db.models import RecipeStatus  # noqa: E402
from app.planner.research import OFFLINE_NOTE, OFFLINE_SOURCE, WebMenuResearch  # noqa: E402
from app.planner.service import MealPlannerService  # noqa: E402
from test_no_repeat import WEEK  # noqa: E402


class QuotaWeb(FakeWeb):
    """Google araması 429 verir; aramasız JSON isteği çalışır."""

    def __init__(self, error=None):
        super().__init__()
        self.error = error or errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                                  "message": "Resource has been exhausted"}})

    async def search_text(self, prompt):
        self.searches.append(prompt)
        raise self.error

    async def ask_json(self, prompt, schema):
        await FakeWeb.search_text(self, prompt)  # satırları hedeflerden üretir
        self.searches.pop()
        self.structured.append(prompt)
        return json.dumps({"tarifler": [{k: v for k, v in r.items() if k != "kaynak"} for r in self.rows]})


@pytest.mark.asyncio
async def test_search_quota_does_not_leave_the_user_empty_handed(db, settings):
    settings = configured(settings)
    fake = QuotaWeb()
    research = WebMenuResearch(settings, fake.search_text, fake.ask_json)

    session = await MealPlannerService(db, settings, research).create_or_get_weekly_session(WEEK)

    assert research.offline is True
    assert len(fake.searches) == 1  # kotaya takılan arama tekrar tekrar denenmez
    assert "internete bakmadan" in fake.structured[0] and "kaynak URL" not in fake.structured[0]
    items = session.meal_plan.items
    assert len(items) == 18 and all(i.recipe.status == RecipeStatus.CANDIDATE for i in items)
    assert all(i.recipe.source == OFFLINE_SOURCE and i.recipe.notes for i in items)


@pytest.mark.asyncio
async def test_other_search_errors_still_stop_without_changes(db, settings):
    from app.planner.research import MenuResearchError

    settings = configured(settings)
    fake = QuotaWeb(errors.ClientError(400, {"error": {"code": 400, "message": "Invalid schema"}}))
    with pytest.raises(MenuResearchError):
        await MealPlannerService(db, settings, WebMenuResearch(settings, fake.search_text, fake.ask_json)).create_or_get_weekly_session(WEEK)
    assert fake.structured == []


@pytest.mark.asyncio
async def test_bulk_new_dishes_say_when_they_came_without_search(db, settings, monkeypatch):
    from test_no_repeat import plan, toolset_for

    settings = configured(settings)
    session = plan(db, [(0, "dinner_main", "Fırında Tavuk"), (1, "dinner_main", "Kuru Fasulye")])
    fake = QuotaWeb()
    _, tools = toolset_for(db, settings, fake)
    out = await tools["yenisiyle_degistir"].call({"ogunler": [WEEK.isoformat(), (WEEK + timedelta(days=1)).isoformat()]})
    assert out.startswith(OFFLINE_NOTE), out
    assert all(i.recipe.source == OFFLINE_SOURCE for i in session.meal_plan.items)


def test_quota_ids_are_logged_for_diagnosis():
    from app.agent.gemini_backend import quota_ids

    assert quota_ids(quota_error("Day")) == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
