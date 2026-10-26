from datetime import date, timedelta
import hashlib
import hmac

from app.db.models import MealPlan, MealPlanItem, Recipe, SessionState, WeeklyPlanningSession
from tests.test_app_api import AUTH, TOKEN, api_settings, client, factory  # noqa: F401

READ = {"Authorization": "Bearer " + hmac.new(TOKEN.encode(), b"foody-caltrack-read-v1", hashlib.sha256).hexdigest()}
DAY = date(2026, 10, 26)


def seed_day(factory, state=SessionState.APPROVED):
    with factory() as db:
        recipe = db.query(Recipe).first()
        recipe_id = recipe.id
        week = WeeklyPlanningSession(week_start=DAY, week_end=DAY + timedelta(days=6), state=state)
        week.meal_plan = MealPlan(items=[
            MealPlanItem(date=DAY, meal_slot="dinner_main", recipe=recipe),
            MealPlanItem(date=DAY, meal_slot="dinner_side", recipe=recipe),
        ])
        db.add(week)
        db.commit()
        return week.id, recipe_id


def test_reader_is_scoped_and_requires_auth(client):
    assert client.get('/api/v1/caltrack/yemekler?tarih=2026-10-26').status_code == 401
    assert client.get('/api/v1/durum', headers=READ).status_code == 401
    assert client.post('/api/v1/menu/onayla', headers=READ, json={}).status_code == 401
    assert client.get('/api/v1/caltrack/yemekler?tarih=bad', headers=READ).status_code == 422


def test_day_is_exact_approved_and_deduplicated(client, factory):
    week_id, recipe_id = seed_day(factory)
    body = client.get('/api/v1/caltrack/yemekler?tarih=2026-10-26', headers=READ).json()
    assert body['tarih'] == '2026-10-26'
    assert body['plan_id'] == week_id
    assert [f['id'] for f in body['yemekler']] == [recipe_id]
    assert {'malzemeler', 'hazirlanis', 'kcal', 'protein', 'porsiyon', 'tahmini'} <= body['yemekler'][0].keys()
    tomorrow = client.get('/api/v1/caltrack/yemekler?tarih=2026-10-27', headers=READ).json()
    assert tomorrow['yemekler'] == []
    absent = client.get('/api/v1/caltrack/yemekler?tarih=2026-11-03', headers=READ).json()
    assert absent['plan_id'] is None and absent['yemekler'] == []
    assert client.get('/api/v1/caltrack/yemekler?tarih=2026-10-26', headers=AUTH).json() == body


def test_draft_never_leaks_or_creates_a_new_plan(client, factory):
    seed_day(factory, SessionState.AWAITING_APPROVAL)
    body = client.get('/api/v1/caltrack/yemekler?tarih=2026-10-26', headers=READ).json()
    assert body['plan_id'] is None and body['yemekler'] == []
    with factory() as db:
        assert db.query(WeeklyPlanningSession).count() == 1


def test_weekly_meze_is_available_all_week_not_next_week(client, factory):
    week_id, recipe_id = seed_day(factory)
    with factory() as db:
        week = db.get(WeeklyPlanningSession, week_id)
        week.meal_plan.items[0].meal_slot = 'hafta_meze_1'
        db.commit()
    body = client.get('/api/v1/caltrack/yemekler?tarih=2026-11-01', headers=READ).json()
    assert body['yemekler'][0]['id'] == recipe_id
    assert body['yemekler'][0]['haftalik'] is True
    assert client.get('/api/v1/caltrack/yemekler?tarih=2026-11-02', headers=READ).json()['yemekler'] == []
