from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agent.tools import MealAgentToolset
from app.db.models import (
    Feedback,
    MealPlan,
    MealPlanItem,
    RecipeStatus,
    SessionState,
    WeeklyPlanningSession,
)
from app.formatting import split_for_telegram
from app.planner.dates import next_week_start, this_week_start
from app.planner.service import MealPlannerService
from app.recipes.service import RecipeService

# Araclar haftayi gercek takvime gore cozdugu icin testler de oyle yapar;
# sabit bir tarih yazmak testi belirli bir gune bagimli kilardi.
WEEK = next_week_start(timezone="Europe/Istanbul")
WEEK_DAY_NAME = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")[WEEK.weekday()]


@pytest.fixture()
def toolset(db, settings):
    """Araclari test oturumuna baglar (her arac ayni oturumu kullanir)."""

    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    return MealAgentToolset(settings, _Factory())


def tool(toolset, name):
    return next(t for t in toolset.build() if t.name == name)


async def call(toolset, name, **kwargs):
    return await tool(toolset, name).call(kwargs)


# --- plani_getir --------------------------------------------------------


@pytest.mark.asyncio
async def test_plani_getir_lists_every_course(db, settings, toolset):
    await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)

    out = await call(toolset, "plani_getir", hafta="gelecek_hafta")

    assert f"{WEEK.isoformat()} {WEEK_DAY_NAME}:" in out
    assert out.count("slot=") == 7 * len(settings.planning_slots)
    assert f"Hafta: {WEEK.isoformat()}" in out


@pytest.mark.asyncio
async def test_plani_getir_without_plan_is_explicit(toolset):
    assert "plan yok" in await call(toolset, "plani_getir", hafta="gelecek_hafta")


# --- tarif_ara / tarif_detay -------------------------------------------


@pytest.mark.asyncio
async def test_tarif_ara_matches_on_ingredient_not_just_name(toolset):
    out = await call(toolset, "tarif_ara", sorgu="kıyma")

    assert "Izgara Köfte" in out


@pytest.mark.asyncio
async def test_tarif_ara_filters_by_category(toolset):
    out = await call(toolset, "tarif_ara", kategori="meze")

    assert "Haydari" in out
    assert "Fırında Tavuk" not in out


@pytest.mark.asyncio
async def test_tarif_ara_miss_suggests_adding(toolset):
    out = await call(toolset, "tarif_ara", sorgu="pad thai")

    assert "bulunamadı" in out


@pytest.mark.asyncio
async def test_tarif_detay_returns_quantities(toolset):
    out = await call(toolset, "tarif_detay", tarif_adi="Fırında Tavuk")

    assert "1000 g tavuk" in out


# --- ogun_degistir -----------------------------------------------------


@pytest.mark.asyncio
async def test_ogun_degistir_swaps_and_records_reason(db, settings, toolset):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    before = {(i.date, i.meal_slot): i.recipe.name for i in session.meal_plan.items}
    version = session.draft_version
    target = next(i for i in session.meal_plan.items if i.date == WEEK and i.recipe.category == "main")

    out = await call(
        toolset,
        "ogun_degistir",
        tarih=WEEK.isoformat(),
        yeni_tarif="Kuru Fasulye",
        gerekce="Beş haftadır baklagil yok.",
        ogun_slotu=target.meal_slot,
    )

    assert "Değiştirildi" in out
    after = {(i.date, i.meal_slot): i.recipe.name for i in session.meal_plan.items}
    assert after[(WEEK, target.meal_slot)] == "Kuru Fasulye"
    # Yalnizca hedeflenen ogun degisti
    assert [k for k in before if before[k] != after[k]] == [(WEEK, target.meal_slot)]
    # Gerekce hafizaya yazildi
    feedback = db.scalars(select(Feedback)).all()
    assert len(feedback) == 1
    assert feedback[0].admin_text == "Beş haftadır baklagil yok."
    assert feedback[0].context["source"] == "agent"
    assert session.draft_version == version + 1
    assert session.state == SessionState.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_ogun_degistir_asks_instead_of_guessing_when_ambiguous(db, settings, toolset):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    # Iki meze slotu ayni kategoriye sahip -> hangisi belirsiz
    mezes = [i for i in session.meal_plan.items if i.date == WEEK and i.recipe.category in {"meze", "salad"}]
    for item in mezes:
        item.recipe_id = RecipeService(db).find_recipe("Haydari").id
        item.recipe = RecipeService(db).find_recipe("Haydari")
    db.commit()

    out = await call(
        toolset,
        "ogun_degistir",
        tarih=WEEK.isoformat(),
        yeni_tarif="Çoban Salata",
        gerekce="Çeşitlilik.",
    )

    assert "belirsiz" in out
    assert "dinner_meze_1" in out and "dinner_meze_2" in out
    assert all(i.recipe.name == "Haydari" for i in mezes)


@pytest.mark.asyncio
async def test_ogun_degistir_refuses_published_plan(db, settings, toolset):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(WEEK)
    planner.approve(session)
    session.state = SessionState.PUBLISHED
    db.commit()

    out = await call(
        toolset, "ogun_degistir", tarih=WEEK.isoformat(), yeni_tarif="Nohut", gerekce="deneme"
    )

    assert "değiştirilemez" in out
    assert "/regenerate" in out


@pytest.mark.asyncio
async def test_ogun_degistir_rejects_unknown_recipe(db, settings, toolset):
    await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)

    out = await call(
        toolset, "ogun_degistir", tarih=WEEK.isoformat(), yeni_tarif="Suşi Burrito", gerekce="x"
    )

    assert "kütüphanede yok" in out


@pytest.mark.asyncio
async def test_ogun_degistir_rejects_date_outside_plan(db, settings, toolset):
    await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)

    outside = (WEEK + timedelta(weeks=5)).isoformat()

    out = await call(toolset, "ogun_degistir", tarih=outside, yeni_tarif="Nohut", gerekce="x")

    assert "planda yok" in out


@pytest.mark.asyncio
async def test_ogun_degistir_rejects_bad_date_format(db, settings, toolset):
    await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)

    assert "ISO tarih değil" in await call(
        toolset, "ogun_degistir", tarih="salı", yeni_tarif="Nohut", gerekce="x"
    )


# --- gecmis_getir ------------------------------------------------------


@pytest.mark.asyncio
async def test_gecmis_getir_ignores_unapproved_drafts(db, settings, toolset):
    """Taslak planlar 'yapilmis yemek' sayilmamali (MEM-02)."""
    monday = this_week_start(timezone=settings.timezone)
    for offset, state in ((1, SessionState.PUBLISHED), (2, SessionState.AWAITING_ADMIN_FEEDBACK)):
        week = monday - timedelta(weeks=offset)
        session = WeeklyPlanningSession(week_start=week, week_end=week + timedelta(days=6), state=state)
        plan = MealPlan(session=session, status="final")
        name = "Izgara Köfte" if state == SessionState.PUBLISHED else "Izgara Balık"
        plan.items.append(
            MealPlanItem(date=week, meal_slot="dinner_main", recipe_id=RecipeService(db).find_recipe(name).id)
        )
        db.add(session)
    db.commit()

    out = await call(toolset, "gecmis_getir", hafta_sayisi=6)

    assert "Izgara Köfte" in out
    assert "Izgara Balık" not in out


@pytest.mark.asyncio
async def test_gecmis_getir_without_history_is_explicit(toolset):
    assert "kaydı yok" in await call(toolset, "gecmis_getir", hafta_sayisi=4)


# --- alisveris_listesi / tercih_kaydet ---------------------------------


@pytest.mark.asyncio
async def test_alisveris_listesi_is_categorised(db, settings, toolset):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(WEEK)
    planner.approve(session)

    out = await call(toolset, "alisveris_listesi", hafta="gelecek_hafta")

    assert "haftası için:" in out
    assert "[Et / Tavuk / Balık]" in out or "[Sebze & Meyve]" in out


@pytest.mark.asyncio
async def test_tercih_kaydet_stores_typed_rule(db, toolset):
    from app.memory.preferences import PreferenceService

    out = await call(toolset, "tercih_kaydet", kural="Kırmızı et haftada en fazla bir kez", tip="soft")

    assert "Kaydedildi (soft)" in out
    assert PreferenceService(db).soft_rules() == ["Kırmızı et haftada en fazla bir kez"]
    assert PreferenceService(db).hard_rules() == []


@pytest.mark.asyncio
async def test_tercih_kaydet_ignores_empty(db, toolset):
    from app.memory.preferences import PreferenceService

    assert "boş" in await call(toolset, "tercih_kaydet", kural="   ")
    assert PreferenceService(db).active() == []


# --- arac semalari -----------------------------------------------------


def test_every_tool_has_a_described_schema(toolset):
    tools = toolset.build()

    assert {t.name for t in tools} == {
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
    }
    for t in tools:
        schema = t.input_schema
        assert t.description, f"{t.name} aciklamasiz"
        assert schema["additionalProperties"] is False
        for field, spec in schema["properties"].items():
            assert spec.get("description"), f"{t.name}.{field} aciklamasiz"


def test_hafta_parameter_is_constrained_to_known_values(toolset):
    schema = tool(toolset, "plani_getir").input_schema["properties"]["hafta"]

    assert set(schema["enum"]) == {"aktif", "bu_hafta", "gelecek_hafta"}


# --- mesaj bolme -------------------------------------------------------


def test_split_for_telegram_respects_limit_and_newlines():
    text = "\n".join(f"satir {i}" * 20 for i in range(60))

    chunks = split_for_telegram(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "".join(chunks.copy()).replace("\n", "") == text.replace("\n", "")


def test_split_for_telegram_keeps_short_text_whole():
    assert split_for_telegram("kısa mesaj") == ["kısa mesaj"]


def test_split_for_telegram_drops_empty():
    assert split_for_telegram("\n  \n") == []


# --- malzeme satiri ayristirici ----------------------------------------


@pytest.mark.parametrize(
    ("line", "quantity", "unit", "name"),
    [
        ("600 gr tavuk göğsü", 600.0, "gr", "tavuk göğsü"),
        ("2 adet kırmızı biber", 2.0, "adet", "kırmızı biber"),
        ("1 yemek kaşığı zeytinyağı", 1.0, "yemek kaşığı", "zeytinyağı"),
        ("1,5 su bardağı pirinç", 1.5, "su bardağı", "pirinç"),
        ("3 diş sarımsak", 3.0, "diş", "sarımsak"),
        ("tuz", None, None, "tuz"),
        ("2 soğan", 2.0, None, "soğan"),
    ],
)
def test_parse_ingredient(line, quantity, unit, name):
    from app.agent.tools import parse_ingredient

    parsed = parse_ingredient(line)

    assert (parsed.quantity, parsed.unit, parsed.name) == (quantity, unit, name)


# --- tarif_ekle / aday_tarifler / tarif_onayla / tarif_cikar ----------


@pytest.mark.asyncio
async def test_tarif_ekle_saves_as_candidate_not_approved(db, toolset):
    out = await call(
        toolset,
        "tarif_ekle",
        ad="Fıstık Ezmeli Noodle",
        kategori="main",
        malzemeler=["250 gr noodle", "2 yemek kaşığı fıstık ezmesi", "1 diş sarımsak"],
        hazirlanis="Noodle'ı haşla, sosu karıştır.",
        kaynak="https://ornek.com/noodle",
    )

    assert "aday tariflere eklendi" in out
    recipe = RecipeService(db).find_recipe("Fıstık Ezmeli Noodle")
    assert recipe.status == RecipeStatus.CANDIDATE
    assert recipe.source == "https://ornek.com/noodle"
    assert recipe.instructions == "Noodle'ı haşla, sosu karıştır."
    # Malzemeler ayristi, talimat malzemeye karismadi
    assert {i.ingredient.name for i in recipe.ingredients} == {"noodle", "fıstık ezmesi", "sarımsak"}
    # Aday oldugu icin planlamaya girmez
    assert "Fıstık Ezmeli Noodle" not in {r.name for r in RecipeService(db).list_recipes()}


@pytest.mark.asyncio
async def test_tarif_ekle_refuses_without_ingredients(db, toolset):
    out = await call(toolset, "tarif_ekle", ad="Boş Tarif", kategori="main", malzemeler=[])

    assert "Malzeme listesi boş" in out
    assert RecipeService(db).find_recipe("Boş Tarif", include_inactive=True) is None


@pytest.mark.asyncio
async def test_tarif_ekle_does_not_overwrite_an_approved_recipe(db, toolset):
    out = await call(
        toolset, "tarif_ekle", ad="Fırında Tavuk", kategori="main", malzemeler=["1 adet tavuk"]
    )

    assert "zaten onaylı" in out
    recipe = RecipeService(db).find_recipe("Fırında Tavuk")
    assert recipe.status == RecipeStatus.APPROVED
    assert len(recipe.ingredients) == 2  # orijinal malzemeler korundu


@pytest.mark.asyncio
async def test_candidate_lifecycle_through_tools(db, toolset):
    await call(toolset, "tarif_ekle", ad="Fellah Köftesi", kategori="meze", malzemeler=["2 su bardağı ince bulgur"])

    listed = await call(toolset, "aday_tarifler")
    assert "Fellah Köftesi" in listed
    assert "menülere girmezler" in listed

    approved = await call(toolset, "tarif_onayla", tarif_adi="Fellah Köftesi")
    assert "onaylandı" in approved
    assert RecipeService(db).find_recipe("Fellah Köftesi").status == RecipeStatus.APPROVED
    # Onaylaninca aday listesinden cikar, planlamaya girer
    assert "Fellah Köftesi" not in await call(toolset, "aday_tarifler")
    assert "Fellah Köftesi" in {r.name for r in RecipeService(db).list_recipes()}


@pytest.mark.asyncio
async def test_tarif_onayla_reports_unknown_name(toolset):
    out = await call(toolset, "tarif_onayla", tarif_adi="Olmayan Tarif")

    assert "bulamadım" in out
    assert "aday_tarifler" in out


@pytest.mark.asyncio
async def test_aday_tarifler_empty_is_explicit(toolset):
    assert "aday tarif yok" in await call(toolset, "aday_tarifler")


@pytest.mark.asyncio
async def test_tarif_cikar_removes_from_planning(db, toolset):
    out = await call(toolset, "tarif_cikar", tarif_adi="Makarna")

    assert "pasifleştirildi" in out
    assert "Makarna" not in {r.name for r in RecipeService(db).list_recipes()}
