"""Menüde çoklu seçimle değişiklik (uygulama 1.12).

Kullanıcı: "Menü taslağında çoklu seçimle değişiklik isteyebileyim, tek tek
değişiklik istemek zor." Seçilenler tek işte değişir; iş arka planda çalışır,
uygulama kısa isteklerle sorar (bağlantı koparsa iş kaybolmaz).
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import app.agent.tools as tools_module
from app.api import create_api_app
from app.planner.service import MealPlannerService
from test_no_repeat import AUTH, WEEK, FakeEstimator, app_settings, factory, idea  # noqa: F401


def _wait(client, job_id, tries=300):
    for _ in range(tries):
        body = client.get(f"/api/v1/is/{job_id}", headers=AUTH).json()
        if body["durum"] != "calisiyor":
            return body
        time.sleep(0.02)
    raise AssertionError("iş bitmedi")


def _with_estimator(monkeypatch, estimator):
    original = tools_module.MealAgentToolset.__init__

    def init(self, settings, session_factory, **kwargs):
        kwargs["estimator"] = estimator
        original(self, settings, session_factory, **kwargs)

    monkeypatch.setattr(tools_module.MealAgentToolset, "__init__", init)


async def _mains(factory, settings, days=(0, 1, 2)):
    from datetime import timedelta

    with factory() as db:
        session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
        dates = {(WEEK + timedelta(days=d)).isoformat() for d in days}
        return [
            {"tarih": i.date.isoformat(), "slot": i.meal_slot}
            for i in session.meal_plan.items
            if i.date.isoformat() in dates and i.meal_slot.endswith("main")
        ]


@pytest.mark.asyncio
async def test_selected_meals_are_replaced_together_in_one_request(factory, app_settings, monkeypatch):
    chosen = await _mains(factory, app_settings)
    estimator = FakeEstimator([
        idea("Tavuklu Pad Thai", "300 gr pirinç eriştesi", "400 gr tavuk göğsü", icin=1),
        idea("Kuzu Tagine", "600 gr kuzu", "1 adet ayva", icin=2),
        idea("Mantarlı Risotto", "300 gr arborio pirinci", "250 gr mantar", icin=3),
    ])
    _with_estimator(monkeypatch, estimator)
    client = TestClient(create_api_app(app_settings, factory, agent=object()))

    started = client.post("/api/v1/menu/toplu/baslat", headers=AUTH, json={
        "islem": "yenisi", "ogunler": chosen, "istek": "daha hafif", "hafta": "gelecek_hafta",
    }).json()
    body = _wait(client, started["is"])

    assert body["durum"] == "bitti", body
    result = body["sonuc"]
    assert len(estimator.prompts) == 1  # hepsi tek istekte: öneriler birbirini görür
    assert "daha hafif" in estimator.prompts[0]
    new = {d["yeni"] for d in result["degisiklikler"]}
    assert new == {"Tavuklu Pad Thai", "Kuzu Tagine", "Mantarlı Risotto"}
    assert result["plan_degisti"] is True and result["menu"]["plan"]["onaylanabilir"] is True


@pytest.mark.asyncio
async def test_selected_meals_can_be_removed_together(factory, app_settings):
    chosen = await _mains(factory, app_settings, days=(3, 4))
    client = TestClient(create_api_app(app_settings, factory, agent=None))

    started = client.post("/api/v1/menu/toplu/baslat", headers=AUTH, json={
        "islem": "cikar", "ogunler": chosen, "hafta": "gelecek_hafta",
    }).json()
    body = _wait(client, started["is"])

    assert body["durum"] == "bitti", body
    removed = body["sonuc"]["degisiklikler"]
    assert len(removed) == 2 and all(d["yeni"] is None for d in removed)
    days = {d["tarih"]: d["ogunler"] for d in body["sonuc"]["menu"]["plan"]["gunler"]}
    for meal in chosen:
        assert all(m["slot"] != meal["slot"] for m in days[meal["tarih"]])


def test_bulk_request_needs_at_least_one_meal(factory, app_settings):
    client = TestClient(create_api_app(app_settings, factory, agent=None))
    response = client.post("/api/v1/menu/toplu/baslat", headers=AUTH, json={"islem": "cikar", "ogunler": []})
    assert response.status_code == 422
