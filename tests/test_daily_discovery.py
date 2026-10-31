"""Her gün internetten yeni tarifler.

Kullanıcı: "Asistan her gün internette gezinip, Instagram vs. yerlerden yeni
tarifler eklesin, her gün 10 tane."
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from app.agent.daily_discovery import TAG, discover_daily, expire_old, search_prompt
from app.db.models import Recipe, RecipeStatus
from app.memory.preferences import PreferenceService
from app.recipes.service import RecipeService
from app.scheduler.weekly import build_scheduler

TODAY = date(2026, 11, 2)


def recipe(name, *ingredients, kategori="main", **extra):
    return {
        "ad": name, "kategori": kategori, "malzemeler": list(ingredients) or ["1 adet x", "2 adet y"],
        "hazirlanis": "Pişir.", "kaynak": "Örnek Blog: https://ornek.blog/tarif", **extra,
    }


class FakeGemini:
    def __init__(self, batches):
        self.batches = list(batches)
        self.searches: list[str] = []
        self.structured: list[str] = []

    async def search(self, prompt):
        self.searches.append(prompt)
        return "arama sonucu metni", ["Örnek Blog: https://ornek.blog/tarif"]

    async def ask_json(self, prompt, schema):
        self.structured.append(prompt)
        return json.dumps({"tarifler": self.batches.pop(0) if self.batches else []})


def test_search_prompt_asks_for_popular_recipes_from_the_web_and_social_media():
    prompt = search_prompt(10, TODAY, ["domuz yok"], ["Mercimek Çorbası"])
    assert "Instagram" in prompt and "TikTok" in prompt and "Kasım" in prompt
    assert "14 tarif" in prompt  # birkaçı elenebilir diye fazlası istenir
    assert "domuz yok" in prompt and "Mercimek Çorbası" in prompt


@pytest.mark.asyncio
async def test_saves_new_allowed_recipes_as_candidates(db):
    PreferenceService(db).add("balık kullanma")
    existing = RecipeService(db).list_recipes(include_candidates=True)[0].name
    gemini = FakeGemini([[
        recipe(existing),  # zaten listede
        recipe("Somonlu Poke", "300 gr somon", "1 su bardağı pirinç"),  # kurala aykırı
        recipe("Tavuklu Khao Soi", "600 gr tavuk but", "400 ml hindistan cevizi sütü", mutfak="Tay"),
        recipe("Közlenmiş Biber Muhammara", "3 adet kırmızı biber", "1 su bardağı ceviz", kategori="meze"),
    ]])

    names = await discover_daily(db, gemini.search, gemini.ask_json, count=2, today=TODAY)

    assert names == ["Tavuklu Khao Soi", "Közlenmiş Biber Muhammara"]
    saved = RecipeService(db).find_recipe("Tavuklu Khao Soi")
    assert saved.status == RecipeStatus.CANDIDATE and TAG in saved.tags
    assert saved.cuisine == "Tay" and "ornek.blog" in saved.source and len(saved.ingredients) == 2
    assert RecipeService(db).find_recipe("Közlenmiş Biber Muhammara").category == "meze"
    assert "balık kullanma" in gemini.searches[0]


@pytest.mark.asyncio
async def test_searches_again_when_too_few_survive_and_skips_variants(db):
    gemini = FakeGemini([
        [recipe("Nohutlu Ispanaklı Tagine"), recipe("Ispanaklı Nohut Güveci")],  # ikincisi çeşitleme
        [recipe("Kuzu Kapama"), recipe("Mantar Stroganoff")],
    ])

    names = await discover_daily(db, gemini.search, gemini.ask_json, count=3, today=TODAY)

    assert names == ["Nohutlu Ispanaklı Tagine", "Kuzu Kapama", "Mantar Stroganoff"]
    assert len(gemini.searches) == 2
    assert "Nohutlu Ispanaklı Tagine" in gemini.searches[1]  # ikinci aramada kaçınılacak


@pytest.mark.asyncio
async def test_a_failed_search_saves_nothing_and_does_not_raise(db):
    async def broken(prompt):
        raise RuntimeError("kota")

    assert await discover_daily(db, broken, FakeGemini([]).ask_json, count=5, today=TODAY) == []


@pytest.mark.asyncio
async def test_old_untried_daily_candidates_are_retired_not_deleted(db):
    gemini = FakeGemini([[recipe("Eski Aday"), recipe("Yeni Aday")]])
    await discover_daily(db, gemini.search, gemini.ask_json, count=2, today=TODAY)
    old = RecipeService(db).find_recipe("Eski Aday")
    old.created_at = datetime.now() - timedelta(days=40)
    db.commit()

    assert expire_old(db) == 1

    assert db.get(Recipe, old.id).status == RecipeStatus.INACTIVE
    assert RecipeService(db).find_recipe("Yeni Aday").status == RecipeStatus.CANDIDATE


def test_scheduler_runs_daily_discovery_every_day(settings):
    scheduler = build_scheduler(settings.model_copy(update={"daily_discovery_enabled": True}))
    job = next(j for j in scheduler.get_jobs() if j.id == "daily_recipe_discovery")
    assert "day_of_week='*'" in str(job.trigger) or "day_of_week" not in str(job.trigger)
    off = build_scheduler(settings.model_copy(update={"daily_discovery_enabled": False}))
    assert "daily_recipe_discovery" not in {j.id for j in off.get_jobs()}
