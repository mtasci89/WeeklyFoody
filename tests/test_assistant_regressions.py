from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.bot.handlers import TelegramHandlers
from app.bot.keyboards import approval_keyboard
from app.bot.messages import split_message
from app.db.models import SessionState, PreferenceType
from app.llm.base import Intent
from app.llm.rule_based import RuleBasedLLMProvider
from app.memory.preferences import PreferenceService
from app.planner.revision import RevisionService
from app.planner.service import MealPlannerService
from app.recipes.service import RecipeService
from app.web_panel import create_web_app
from app.workflow import WeeklyWorkflowService


@pytest.mark.asyncio
@pytest.mark.parametrize('message', ['Menüyü onaylama', 'onaylamıyorum', 'adayı onayla'])
async def test_unrelated_or_negative_approval_never_publishes(message):
    result = await RuleBasedLLMProvider().route_intent(message)
    assert result.intent != Intent.APPROVE_PLAN


@pytest.mark.asyncio
@pytest.mark.parametrize('message,day', [('Cumartesi 6 kişi olacağız.', 'saturday'), ('Pazartesi 6 kişi olacağız.', 'monday')])
async def test_day_names_are_not_substrings(message, day):
    result = await RuleBasedLLMProvider().parse_revision(message)
    assert len(result.operations) == 1
    assert result.operations[0].day_name == day
    assert result.operations[0].servings == 6
    assert result.operations[0].instruction is None


@pytest.mark.asyncio
async def test_published_plan_can_be_edited_reapproved_and_sent(db, settings):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(date(2026, 8, 31))
    planner.approve(session)
    notifier = SimpleNamespace(send_message=AsyncMock())
    workflow = WeeklyWorkflowService(db, settings, notifier)
    await workflow.publish_final(session)
    names = {(item.date, item.meal_slot): item.recipe_id for item in session.meal_plan.items}
    await RevisionService(db, settings).revise(session, 'Cumartesi 6 kişi olacağız.')
    assert session.state == SessionState.AWAITING_APPROVAL
    assert session.published_at is None
    assert session.draft_version == 2
    assert session.context['previous_final_version'] == 1
    assert {(item.date, item.meal_slot): item.recipe_id for item in session.meal_plan.items} == names
    assert all(item.servings == 6 for item in session.meal_plan.items if item.date.weekday() == 5)
    assert all(item.servings != 6 for item in session.meal_plan.items if item.date.weekday() != 5)
    with pytest.raises(ValueError):
        await workflow.publish_final(session)
    planner.approve(session)
    assert await workflow.publish_final(session)
    assert notifier.send_message.await_count == 6
    assert not await workflow.publish_final(session)


@pytest.mark.asyncio
async def test_unknown_revision_asks_without_modifying_or_unlocking_final(db, settings):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(date(2026, 8, 31))
    planner.approve(session)
    before = [(i.recipe_id, i.servings) for i in session.meal_plan.items]
    await RevisionService(db, settings).revise(session, 'Bu hafta iki kere tavuk olmasın.')
    assert session.context['clarification']
    assert session.state == SessionState.APPROVED
    assert [(i.recipe_id, i.servings) for i in session.meal_plan.items] == before
    assert session.draft_version == 1


@pytest.mark.asyncio
async def test_revision_rejects_banned_recipe_without_partial_changes(db, settings):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(date(2026, 8, 31))
    before = [(i.recipe_id, i.servings) for i in session.meal_plan.items]
    PreferenceService(db).add('Bundan sonra tavuk önerme.', PreferenceType.HARD)
    with pytest.raises(ValueError):
        await RevisionService(db, settings).revise(session, 'Salı Fırında Tavuk koy.')
    assert [(i.recipe_id, i.servings) for i in session.meal_plan.items] == before
    assert session.draft_version == 1


@pytest.mark.asyncio
async def test_retry_does_not_redeliver_successful_recipients(db, settings):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(date(2026, 8, 31))
    planner.approve(session)
    notifier = SimpleNamespace(send_message=AsyncMock(side_effect=[None, RuntimeError('offline')]))
    workflow = WeeklyWorkflowService(db, settings, notifier)
    with pytest.raises(RuntimeError):
        await workflow.publish_final(session)
    assert session.state == SessionState.APPROVED
    notifier.send_message.reset_mock(side_effect=True)
    await workflow.publish_final(session)
    assert [call.args[0] for call in notifier.send_message.await_args_list] == [222, 333]


@pytest.mark.asyncio
async def test_published_menu_can_be_regenerated(db, settings):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(date(2026, 8, 31))
    planner.approve(session)
    session.state = SessionState.PUBLISHED
    db.commit()
    session = await planner.create_or_get_weekly_session(date(2026, 8, 31), regenerate=True)
    assert session.draft_version == 2
    assert session.meal_plan.status == 'draft'
    assert session.context['previous_final']['meals']


def test_telegram_split_is_safe_with_emoji_and_long_recipe_names():
    text = ('🥗' * 2500 + '\n') * 3
    parts = split_message(text)
    assert len(parts) > 1
    assert all(len(p.encode('utf-16-le')) // 2 <= 3500 for p in parts)


@pytest.mark.asyncio
async def test_stale_telegram_button_does_not_approve(db, settings, monkeypatch):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(date(2026, 8, 31))
    data = approval_keyboard(session).inline_keyboard[0][0].callback_data
    session.draft_version += 1
    db.commit()
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr('app.bot.handlers.SessionLocal', Session)
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(data=data, answer=AsyncMock(), message=message)
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=111), effective_message=message)
    await TelegramHandlers(settings, SimpleNamespace(send_message=AsyncMock())).callback(update, SimpleNamespace(user_data={}))
    db.refresh(session)
    assert session.state != SessionState.APPROVED
    assert 'Menü değişmiş' in message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_web_assistant_edits_final_and_blocks_stale_approval(db, settings):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(date(2026, 8, 31))
    planner.approve(session)
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    notifier = SimpleNamespace(send_message=AsyncMock())
    client = TestClient(create_web_app(settings, Session, notifier))
    body = {'session_id': session.id, 'version': 1, 'action': 'chat', 'message': 'Cumartesi 6 kişi olacağız.'}
    response = client.post('/api/assistant', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['plan']['version'] == 2
    assert response.json()['plan']['state'] == 'AWAITING_APPROVAL'
    stale = client.post('/api/assistant', json={**body, 'action': 'approve'})
    assert stale.status_code == 409
    final = client.post('/api/assistant', json={**body, 'action': 'approve', 'version': 2})
    assert final.status_code == 200
    assert final.json()['plan']['state'] == 'PUBLISHED'
    assert notifier.send_message.await_count == 3


def test_assistant_auth_and_screen(db, settings):
    settings.web_panel_token = 'a&<token>'
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    client = TestClient(create_web_app(settings, Session))
    assert client.post('/api/assistant', json={'action': 'generate'}).status_code == 401
    response = client.get('/', headers={'x-panel-token': settings.web_panel_token})
    assert response.status_code == 200
    assert 'a&amp;&lt;token&gt;' in response.text
    assert 'a&<token>' not in response.text
    assert 'Alışveriş listesi' in response.text


@pytest.mark.asyncio
async def test_edit_waits_for_publishing_and_remains_an_unpublished_draft(db, settings):
    import asyncio
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(date(2026, 8, 31))
    planner.approve(session)
    started = asyncio.Event()
    async def send(*args, **kwargs):
        started.set()
        await asyncio.sleep(0.01)
    publishing = asyncio.create_task(WeeklyWorkflowService(db, settings, SimpleNamespace(send_message=send)).publish_final(session))
    await started.wait()
    revising = asyncio.create_task(RevisionService(db, settings).revise(session, 'Cumartesi 6 kişi olacağız.'))
    await asyncio.gather(publishing, revising)
    assert session.state == SessionState.AWAITING_APPROVAL
    assert session.draft_version == 2
    assert session.published_at is None


@pytest.mark.asyncio
async def test_recipe_instructions_are_not_confused_with_menu_changes():
    router = RuleBasedLLMProvider()
    result = await router.route_intent('Tavuk Fajita\n600 gr tavuk\n2 biber\nTavuğu tavaya koy ve pişir.')
    assert result.intent == Intent.ADD_RECIPE
    result = await router.route_intent('Salı balığı çıkar.\nÇarşamba 6 kişi olacağız.')
    assert result.intent == Intent.MODIFY_PLAN


@pytest.mark.asyncio
async def test_followup_recipe_name_completes_revision(db, settings):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(date(2026, 8, 31))
    revision = RevisionService(db, settings)
    await revision.revise(session, 'Salı Bilinmeyen yemek koy.')
    assert session.context['clarification']
    await revision.revise(session, 'Kuru Fasulye')
    assert not session.context.get('clarification')
    assert any(i.recipe.name == 'Kuru Fasulye' for i in session.meal_plan.items if i.date.weekday() == 1)
