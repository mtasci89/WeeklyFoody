"""Exercise actual SDK response/error boundaries, without live credentials."""
import re

import pytest
from google.genai import errors

from app.agent.gemini_backend import GeminiBackend, GeminiCapabilityError
from app.db.models import SessionState
from app.memory.rules import MealRules
from app.planner.research import MenuResearchError, Target, WebMenuResearch, research_failure
from test_agent_gemini import FakeGeminiClient, text_response
from test_menu_research import FakeWeb, configured
from test_no_repeat import WEEK, plan, toolset_for


def provider_error(code, message):
    return errors.ClientError(code, {"error": {"code": code, "message": message}})


def backend(settings, responses):
    client = FakeGeminiClient(responses)
    config = settings.model_copy(update={"gemini_model": "primary", "gemini_fallback_models": ["backup"]})
    return GeminiBackend(config, client), client


@pytest.mark.asyncio
async def test_unsupported_search_moves_to_capable_model_without_disabling_chat(settings):
    sdk, client = backend(settings, [
        provider_error(400, "Google Search grounding is not supported for this model"),
        text_response("Tarif", sources=[("Kaynak", "https://recipes.example/yemek")]),
        text_response("Sohbet çalışıyor"),
    ])
    text, sources = await sdk.search_text("bir tarif ara")
    assert text == "Tarif" and sources == ["Kaynak: https://recipes.example/yemek"]
    assert await sdk.ping() == "Sohbet çalışıyor"
    assert [r["model"] for r in client.requests] == ["primary", "backup", "primary"]


@pytest.mark.asyncio
async def test_unsupported_search_is_remembered_for_next_search(settings):
    sdk, client = backend(settings, [provider_error(400, "google_search tool is unsupported"), text_response("A"), text_response("B")])
    await sdk.search_text("ilk")
    await sdk.search_text("ikinci")
    assert [r["model"] for r in client.requests] == ["primary", "backup", "backup"]


@pytest.mark.asyncio
async def test_unsupported_json_can_use_another_model(settings):
    sdk, client = backend(settings, [provider_error(400, "JSON response_schema is not supported by this model"), text_response('{"ok":true}')])
    assert await sdk.generate_json("yapılandır", {"type": "object"}) == '{"ok":true}'
    assert [r["model"] for r in client.requests] == ["primary", "backup"]


@pytest.mark.parametrize("message", ["API key not valid", "Invalid schema: required property missing"])
@pytest.mark.asyncio
async def test_auth_and_bad_schema_errors_are_not_hidden_with_model_fallback(settings, message):
    sdk, client = backend(settings, [provider_error(400, message)])
    with pytest.raises(errors.ClientError):
        await sdk.search_text("ara")
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_all_incompatible_models_report_unsupported_instead_of_looping(settings):
    sdk, client = backend(settings, [provider_error(400, "Google Search is not supported"), provider_error(400, "grounding unsupported")])
    with pytest.raises(errors.ClientError):
        await sdk.search_text("ilk")
    with pytest.raises(GeminiCapabilityError, match="Google araması"):
        await sdk.search_text("ikinci")
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_quota_on_capable_model_is_not_hidden_by_incompatible_backup(settings):
    sdk, client = backend(settings, [provider_error(429, "Quota reached"),
                                   provider_error(400, "Google Search is unsupported"), text_response("Recovered")])
    with pytest.raises(errors.ClientError) as caught:
        await sdk.search_text("ilk")
    assert caught.value.code == 429
    text, _ = await sdk.search_text("tekrar")
    assert text == "Recovered"
    assert [r["model"] for r in client.requests] == ["primary", "backup", "primary"]


@pytest.mark.parametrize(("code", "message", "expected"), [
    (429, "Quota reached; secret=AIza-PRIVATE", "kotası aşıldı (429)"),
    (403, "Permission denied", "erişimini reddetti (403)"),
    (400, "Billing account required", "ücretlendirme/erişim"),
    (400, "API key invalid: AIza-PRIVATE", "anahtarı kabul edilmedi"),
    (404, "Model missing", "modelleri bulunamadı"),
])
def test_actual_provider_reason_survives_without_secrets(code, message, expected):
    text = research_failure(provider_error(code, message), "Google araması")
    assert expected in text and "Google araması:" in text
    assert "AIza-PRIVATE" not in text and "secret=" not in text


@pytest.mark.asyncio
async def test_search_quota_reaches_bulk_tool_message_and_preserves_approved_menu(db, settings):
    old = plan(db, [(0, "dinner_main", "Fırında Tavuk")])
    old.state = SessionState.APPROVED
    db.commit()
    fake = FakeWeb()
    async def quota(prompt):
        raise provider_error(429, "Quota reached")
    fake.search_text = quota
    _, tools = toolset_for(db, configured(settings), fake)
    text = await tools["yenisiyle_degistir"].call({"ogunler": [f"{WEEK}|dinner_main"]})
    # Kotada aramasız öneri denenir (tests/test_gemini_quota.py); o da boş dönerse neden yine söylenir.
    assert text.startswith("Google araması:") and "429" in text and "Menü değiştirilmedi" in text
    assert old.state == SessionState.APPROVED
    assert old.meal_plan.items[0].recipe.name == "Fırında Tavuk"


@pytest.mark.asyncio
async def test_json_quota_is_distinguished_from_search_error(settings):
    fake = FakeWeb()
    async def quota(prompt, schema):
        raise provider_error(429, "Quota reached")
    search = WebMenuResearch(settings, fake.search_text, quota)
    with pytest.raises(MenuResearchError, match="Tarif yanıtını hazırlama:.*429"):
        await search.find([Target(WEEK, "dinner_main", "main")], [], [], MealRules())


@pytest.mark.asyncio
async def test_eight_targets_are_searched_in_bounded_groups(settings):
    counts = []
    fake = FakeWeb()
    async def limited(prompt):
        count = len(re.findall(r"^\d+\) \d{4}-\d{2}-\d{2}:", prompt, re.M))
        counts.append(count)
        assert count <= 4, "provider payload would be too large"
        return await fake.search_text(prompt)
    from datetime import timedelta
    targets = [Target(WEEK + timedelta(days=i), "dinner_main", "main") for i in range(7)]
    targets += [Target(WEEK, "dinner_side", "side")]
    result = await WebMenuResearch(settings, limited, fake.ask_json).find(targets, [], [], MealRules())
    assert len(result) == 8 and counts == [4, 3, 1]
    assert "Yeni ana yemek: Limonlu Hindi Kapama" in fake.searches[-1]
