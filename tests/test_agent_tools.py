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
from app.config import course_role
from app.formatting import split_for_telegram
from app.recipes.importer import IngredientInput, RecipeInput
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

    assert "1 kg tavuk" in out


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
async def test_ogun_degistir_reopens_an_approved_plan(db, settings, toolset):
    """Telegram yok; onay yalnızca kesinleştirme. Değişiklik istenirse menü taslağa döner."""
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(WEEK)
    planner.approve(session)
    session.state = SessionState.PUBLISHED
    db.commit()
    main = next(i for i in session.meal_plan.items if i.date == WEEK and i.recipe.category == "main")
    other = "Nohut" if main.recipe.name != "Nohut" else "Kuru Fasulye"

    out = await call(
        toolset, "ogun_degistir", tarih=WEEK.isoformat(), yeni_tarif=other, gerekce="deneme", ogun_slotu=main.meal_slot
    )

    assert "Değiştirildi" in out and "yeniden taslağa döndü" in out
    assert session.state == SessionState.AWAITING_APPROVAL


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


# --- alisveris_listesi / ev kurallari ---------------------------------


@pytest.mark.asyncio
async def test_alisveris_listesi_is_categorised(db, settings, toolset):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(WEEK)
    planner.approve(session)

    out = await call(toolset, "alisveris_listesi", hafta="gelecek_hafta")

    assert "haftası için:" in out
    assert "[Et / Tavuk / Balık]" in out or "[Sebze & Meyve]" in out


@pytest.mark.asyncio
async def test_kural_ekle_stores_rule(toolset):
    out = await call(toolset, "kural_ekle", kural="Balık kullanma.")

    assert "Kural eklendi" in out
    assert "Yasaklanan içerikler" in out
    assert toolset.rules.active() == ["Balık kullanma."]


@pytest.mark.asyncio
async def test_kural_ekle_ignores_empty_and_duplicates(toolset):
    assert "boş" in await call(toolset, "kural_ekle", kural="   ")
    await call(toolset, "kural_ekle", kural="Protein ağırlıklı olsun")
    assert "zaten var" in await call(toolset, "kural_ekle", kural="protein ağırlıklı olsun")
    assert toolset.rules.active() == ["Protein ağırlıklı olsun"]


@pytest.mark.asyncio
async def test_kural_sil_removes_single_match_and_asks_on_ambiguity(toolset):
    await call(toolset, "kural_ekle", kural="Balık kullanma")
    await call(toolset, "kural_ekle", kural="Öğün başı 1000 kaloriyi geçmesin")
    await call(toolset, "kural_ekle", kural="Akşamları kalori yaz")

    assert "hangisini" in await call(toolset, "kural_sil", ifade="kalori")
    assert "geçen bir kural yok" in await call(toolset, "kural_sil", ifade="domates")
    assert "Kural silindi: Balık kullanma" in await call(toolset, "kural_sil", ifade="balık")
    assert toolset.rules.active() == ["Öğün başı 1000 kaloriyi geçmesin", "Akşamları kalori yaz"]


@pytest.mark.asyncio
async def test_kurallari_goster_lists_rules(toolset):
    assert "Henüz ev kuralı yok" in await call(toolset, "kurallari_goster")
    await call(toolset, "kural_ekle", kural="Her akşam 3 farklı yemek olsun")

    out = await call(toolset, "kurallari_goster")

    assert "1 ev kuralı" in out
    assert "Her akşam 3 farklı yemek olsun" in out


# --- besin_degeri_kaydet ------------------------------------------------


@pytest.mark.asyncio
async def test_besin_degeri_kaydet_stores_estimates_per_serving(db, toolset):
    out = await call(toolset, "besin_degeri_kaydet", degerler=["Izgara Köfte|540|38", "Mercimek Çorbası|210,4"])

    assert "2 tarifin besin değeri tahmini olarak kaydedildi" in out
    service = RecipeService(db)
    kofte = service.find_recipe("Izgara Köfte").nutrition
    corba = service.find_recipe("Mercimek Çorbası").nutrition
    assert (kofte.calories_kcal, kofte.protein_g, kofte.estimated) == (540, 38, True)
    assert "ajan tahmini" in kofte.source
    assert (corba.calories_kcal, corba.protein_g) == (210, None)


@pytest.mark.asyncio
async def test_besin_degeri_kaydet_never_overwrites_user_entered_values(db, toolset):
    from app.recipes.nutrition import NutritionInput, save_nutrition

    kofte = RecipeService(db).find_recipe("Izgara Köfte")
    save_nutrition(db, kofte, NutritionInput(calories_kcal=610, protein_g=40, source="etiket", estimated=False))
    db.commit()

    out = await call(toolset, "besin_degeri_kaydet", degerler=["Izgara Köfte|400|20"])

    assert "üzerine yazmadım" in out
    assert RecipeService(db).find_recipe("Izgara Köfte").nutrition.calories_kcal == 610


@pytest.mark.asyncio
async def test_besin_degeri_kaydet_rejects_bad_rows(db, toolset):
    out = await call(
        toolset,
        "besin_degeri_kaydet",
        degerler=["Olmayan Yemek|300|10", "Izgara Köfte|9000|38", "Izgara Köfte|abc", "sadece ad"],
    )

    assert "Kaydedilemeyenler" in out
    assert "kütüphanede yok" in out
    assert "makul aralıkta değil" in out
    assert "sayı okunamadı" in out
    assert "biçimi yanlış" in out
    assert RecipeService(db).find_recipe("Izgara Köfte").nutrition is None


@pytest.mark.asyncio
async def test_plani_getir_shows_nutrition_and_meal_totals(db, settings, toolset):
    from app.recipes.nutrition import NutritionInput, save_nutrition

    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    for recipe in {item.recipe for item in session.meal_plan.items}:
        save_nutrition(db, recipe, NutritionInput(calories_kcal=300, protein_g=20, source="test"))
    db.commit()

    out = await call(toolset, "plani_getir", hafta="gelecek_hafta")

    assert "300 kcal, 20 g protein / kişi (tahmini)" in out
    assert f"{WEEK} dinner: {300 * len(settings.planning_slots)} kcal (tahmini)" in out


@pytest.mark.asyncio
async def test_plani_getir_says_when_calories_are_unknown(db, settings, toolset):
    await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)

    out = await call(toolset, "plani_getir", hafta="gelecek_hafta")

    assert "toplam kalori bilinmiyor" in out
    assert "kalori/protein bilgisi yok" in out


# --- arac semalari -----------------------------------------------------


def test_every_tool_has_a_described_schema(toolset):
    tools = toolset.build()

    assert {t.name for t in tools} == {
        "plani_getir",
        "tarif_ara",
        "tarif_detay",
        "ogun_degistir",
        "ogun_ekle",
        "ogun_cikar",
        "yenisiyle_degistir",
        "alisveris_listesi",
        "gecmis_getir",
        "kurallari_goster",
        "kural_ekle",
        "kural_sil",
        "besin_degeri_kaydet",
        "menuyu_onayla",
        "kiler",
        "tarif_ekle",
        "aday_tarifler",
        "tarif_onayla",
        "tarif_cikar",
        "plan_hazirla",
        "plan_kaydet",
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
    assert "'yeni' olarak" in listed

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


# --- plan_hazirla / plan_kaydet ---------------------------------------


def week_slots(settings, week_start):
    from app.planner.dates import week_dates

    return [(d.isoformat(), slot) for d in week_dates(week_start) for slot in settings.planning_slots]


def full_week(db, settings, week_start):
    """Her slota rolune uyan bir tarif koyan gecerli bir hafta uretir."""
    from app.agent.tools import selector_matches_role

    recipes = RecipeService(db).list_recipes()
    lines = []
    for iso, slot in week_slots(settings, week_start):
        role = course_role(slot)
        fit = next(r for r in recipes if selector_matches_role(db, r, role))
        lines.append(f"{iso}|{slot}|{fit.name}")
    return lines


@pytest.mark.asyncio
async def test_plan_hazirla_exposes_scores_and_history(db, settings, toolset):
    """MEM-01: puan, son yapilma ve red sayisi modele ulasmali."""
    out = await call(toolset, "plan_hazirla", hafta="gelecek_hafta")

    assert f"Hafta: {WEEK.isoformat()}" in out
    for role in ("main", "meze", "side"):
        assert f"{role} (uygun kategoriler" in out
    assert "p | " in out
    assert "yeni" in out
    assert "Aday havuzu (rol başına, puan sırasına göre)" in out


@pytest.mark.asyncio
async def test_plan_hazirla_refuses_an_approved_week(db, settings, toolset):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(WEEK)
    planner.approve(session)

    out = await call(toolset, "plan_hazirla", hafta="gelecek_hafta")

    assert "onaylanmış" in out


@pytest.mark.asyncio
async def test_plan_kaydet_writes_a_whole_week(db, settings, toolset):
    out = await call(
        toolset,
        "plan_kaydet",
        ogunler=full_week(db, settings, WEEK),
        notlar="Haftaya protein çeşitliliği gözeterek dağıttım.",
    )

    assert "kaydedildi" in out
    session = MealPlannerService(db, settings).current_session(WEEK)
    assert session is not None
    assert len(session.meal_plan.items) == 7 * len(settings.planning_slots)
    assert session.state == SessionState.AWAITING_APPROVAL
    assert session.context["agent_notes"].startswith("Haftaya protein")


@pytest.mark.asyncio
async def test_plan_kaydet_rejects_unknown_recipes(db, settings, toolset):
    lines = full_week(db, settings, WEEK)
    lines[0] = lines[0].rsplit("|", 1)[0] + "|Olmayan Yemek"

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "Olmayan Yemek" in out and "kütüphanede yok" in out
    assert "tarif_ekle" in out
    assert MealPlannerService(db, settings).current_session(WEEK) is None


@pytest.mark.asyncio
async def test_plan_kaydet_puts_new_candidate_dishes_on_the_menu(db, settings, toolset):
    """Kullanıcı: "tarif listesinden dışarı çıkmıyor, her hafta sıradışı şeyler de olsun"."""
    added = await call(
        toolset, "tarif_ekle", ad="Shakshuka", kategori="main",
        malzemeler=["6 adet yumurta", "4 adet domates"], kaynak="ajan önerisi",
    )
    assert "menüye koyabilirsin" in added
    lines = full_week(db, settings, WEEK)
    main = next(i for i, line in enumerate(lines) if "dinner_main" in line)
    lines[main] = lines[main].rsplit("|", 1)[0] + "|Shakshuka"

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "kaydedildi" in out
    assert "Yeni yemekler" in out and "Shakshuka" in out
    assert "UYARI: Bu hafta 2 yeni yemek hedefleniyor, planda 1 var" in out
    assert "[YENİ" in out
    session = MealPlannerService(db, settings).current_session(WEEK)
    names = {i.recipe.name for i in session.meal_plan.items}
    assert "Shakshuka" in names
    # Menüye girmesi onu kalıcı listeye almaz; aile beğenince onaylanır.
    assert RecipeService(db).find_recipe("Shakshuka").status == RecipeStatus.CANDIDATE


@pytest.mark.asyncio
async def test_plan_kaydet_still_rejects_disabled_recipes(db, settings, toolset):
    await call(toolset, "tarif_ekle", ad="Eski Yemek", kategori="main", malzemeler=["1 adet x"])
    await call(toolset, "tarif_cikar", tarif_adi="Eski Yemek")
    lines = full_week(db, settings, WEEK)
    main = next(i for i, line in enumerate(lines) if "dinner_main" in line)
    lines[main] = lines[main].rsplit("|", 1)[0] + "|Eski Yemek"

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "Plan kaydedilmedi" in out
    assert MealPlannerService(db, settings).current_session(WEEK) is None


@pytest.mark.asyncio
async def test_plan_hazirla_asks_for_new_dishes_and_lists_untried_candidates(toolset):
    await call(toolset, "tarif_ekle", ad="Kimchi Pilav", kategori="side", malzemeler=["2 su bardağı pirinç"])

    out = await call(toolset, "plan_hazirla")

    assert "en az 2 yeni yemek" in out
    assert "Denenmemiş aday tarifler" in out and "Kimchi Pilav" in out


@pytest.mark.asyncio
async def test_house_rule_sets_the_weekly_new_dish_count(db, toolset):
    await call(toolset, "kural_ekle", kural="Her hafta 3 sıradışı yemek olsun")
    assert "en az 3 yeni yemek" in await call(toolset, "plan_hazirla")

    await call(toolset, "kural_sil", ifade="sıradışı")
    await call(toolset, "kural_ekle", kural="Yeni yemek ekleme")
    assert "YENİ YEMEKLER" not in await call(toolset, "plan_hazirla")


@pytest.mark.asyncio
async def test_ogun_degistir_accepts_a_new_candidate_dish(db, settings, toolset):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    target = next(i for i in session.meal_plan.items if i.date == WEEK and i.recipe.category == "main")
    await call(toolset, "tarif_ekle", ad="Mantarlı Risotto", kategori="main", malzemeler=["300 gr pirinç"])

    out = await call(
        toolset, "ogun_degistir", tarih=WEEK.isoformat(), yeni_tarif="Mantarlı Risotto",
        gerekce="Farklı bir şey denemek istediler", ogun_slotu=target.meal_slot,
    )

    assert "Değiştirildi" in out
    assert "Mantarlı Risotto" in {i.recipe.name for i in session.meal_plan.items}


@pytest.mark.asyncio
async def test_plan_kaydet_rejects_a_category_mismatch(db, settings, toolset):
    lines = full_week(db, settings, WEEK)
    main_slot = next(i for i, line in enumerate(lines) if "dinner_main" in line)
    lines[main_slot] = lines[main_slot].rsplit("|", 1)[0] + "|Haydari"

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "rolüne uymuyor" in out
    assert MealPlannerService(db, settings).current_session(WEEK) is None


@pytest.mark.asyncio
async def test_plan_kaydet_rejects_malformed_and_duplicate_lines(db, settings, toolset):
    lines = full_week(db, settings, WEEK)
    lines.append("bozuk satır")
    lines.append(lines[0])

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "üç alan değil" in out
    assert "iki kez verilmiş" in out


@pytest.mark.asyncio
async def test_plan_kaydet_replaces_an_existing_draft(db, settings, toolset):
    await call(toolset, "plan_kaydet", ogunler=full_week(db, settings, WEEK))
    first = MealPlannerService(db, settings).current_session(WEEK)
    version = first.draft_version

    out = await call(toolset, "plan_kaydet", ogunler=full_week(db, settings, WEEK))
    assert "zaten" in out and "uzerine_yaz" in out  # yanlışlıkla silinmez
    await call(toolset, "plan_kaydet", ogunler=full_week(db, settings, WEEK), uzerine_yaz=True)

    session = MealPlannerService(db, settings).current_session(WEEK)
    assert len(session.meal_plan.items) == 7 * len(settings.planning_slots)
    assert session.draft_version == version + 1


@pytest.mark.asyncio
async def test_plan_kaydet_refuses_to_overwrite_an_approved_week(db, settings, toolset):
    planner = MealPlannerService(db, settings)
    session = await planner.create_or_get_weekly_session(WEEK)
    planner.approve(session)

    out = await call(toolset, "plan_kaydet", ogunler=full_week(db, settings, WEEK))

    assert "onaylı" in out and "uzerine_yaz" in out
    assert session.state == SessionState.APPROVED


# --- haftanin sekli esnek olmali ---------------------------------------


def shaped_week(db, settings, week_start, roles_per_day, skip_dates=()):
    """Istenen rol dagilimina gore hafta uretir (sabit sablona bagli degil)."""
    from app.agent.tools import selector_matches_role
    from app.planner.dates import week_dates

    recipes = RecipeService(db).list_recipes()
    lines = []
    for day in week_dates(week_start):
        if day.isoformat() in skip_dates:
            continue
        counts: dict[str, int] = {}
        for role in roles_per_day:
            counts[role] = counts.get(role, 0) + 1
            suffix = role if roles_per_day.count(role) == 1 else f"{role}_{counts[role]}"
            fit = next(r for r in recipes if selector_matches_role(db, r, role))
            lines.append(f"{day.isoformat()}|dinner_{suffix}|{fit.name}")
    return lines


@pytest.mark.asyncio
async def test_plan_kaydet_accepts_one_meze_instead_of_two(db, settings, toolset):
    """Kullanici "her gune tek meze" diyebilmeli; sablon dayatilmamali."""
    lines = shaped_week(db, settings, WEEK, ["main", "meze", "side"])

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "kaydedildi" in out
    session = MealPlannerService(db, settings).current_session(WEEK)
    assert len(session.meal_plan.items) == 7 * 3
    monday = [i for i in session.meal_plan.items if i.date == WEEK]
    assert sorted(course_role(i.meal_slot) for i in monday) == ["main", "meze", "side"]


@pytest.mark.asyncio
async def test_plan_kaydet_accepts_a_day_with_only_a_main(db, settings, toolset):
    lines = shaped_week(db, settings, WEEK, ["main", "meze", "side"])
    saturday = (WEEK + timedelta(days=5)).isoformat()
    lines = [l for l in lines if not l.startswith(saturday)]
    lines.append(f"{saturday}|dinner_main|{RecipeService(db).find_recipe('Fırında Tavuk').name}")

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "kaydedildi" in out
    session = MealPlannerService(db, settings).current_session(WEEK)
    assert len([i for i in session.meal_plan.items if i.date.isoformat() == saturday]) == 1


@pytest.mark.asyncio
async def test_plan_kaydet_accepts_an_empty_day(db, settings, toolset):
    """"Pazar dışarıdayız" -> o gun hic ogun olmayabilir."""
    sunday = (WEEK + timedelta(days=6)).isoformat()
    lines = shaped_week(db, settings, WEEK, ["main", "meze"], skip_dates=(sunday,))

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "kaydedildi" in out
    assert "Öğün yazılmayan günler" in out and sunday in out
    session = MealPlannerService(db, settings).current_session(WEEK)
    assert not [i for i in session.meal_plan.items if i.date.isoformat() == sunday]


@pytest.mark.asyncio
async def test_plan_kaydet_reports_per_day_counts(db, settings, toolset):
    out = await call(toolset, "plan_kaydet", ogunler=shaped_week(db, settings, WEEK, ["main", "soup"]))

    assert "Gün başına:" in out
    assert f"{WEEK.isoformat()}=2" in out


@pytest.mark.asyncio
async def test_plan_kaydet_still_rejects_unknown_roles_and_dates(db, settings, toolset):
    lines = shaped_week(db, settings, WEEK, ["main"])
    lines.append(f"{WEEK.isoformat()}|dinner_tatli|Fırında Tavuk")
    lines.append(f"{(WEEK + timedelta(weeks=9)).isoformat()}|dinner_main|Fırında Tavuk")
    lines.append(f"{WEEK.isoformat()}|kahvalti_main|Fırında Tavuk")

    out = await call(toolset, "plan_kaydet", ogunler=lines)

    assert "rolü tanınmıyor" in out
    assert "haftanın dışında" in out
    assert "tanınmıyor; slot adı" in out
    assert MealPlannerService(db, settings).current_session(WEEK) is None


@pytest.mark.asyncio
async def test_plan_kaydet_rejects_an_entirely_empty_week(db, settings, toolset):
    out = await call(toolset, "plan_kaydet", ogunler=[])

    assert "Hiç geçerli öğün verilmedi" in out


@pytest.mark.asyncio
async def test_plan_hazirla_offers_roles_and_calls_the_shape_a_suggestion(db, settings, toolset):
    out = await call(toolset, "plan_hazirla", hafta="gelecek_hafta")

    assert "ZORUNLU DEĞİL" in out
    assert "Önerilen gün şekli" in out
    for role in ("main", "meze", "salad", "side", "soup"):
        assert f"\n{role} (uygun kategoriler" in out
    assert "dinner_meze_1" in out


@pytest.mark.asyncio
async def test_reopening_published_menu_retains_snapshot_and_allows_republish(db, settings, toolset):
    from datetime import datetime
    session = await MealPlannerService(db, settings).create_or_get_weekly_session(WEEK)
    session.state = SessionState.PUBLISHED
    session.meal_plan.status = 'final'
    session.published_at = datetime.utcnow()
    db.commit()
    target = next(i for i in session.meal_plan.items if i.date == WEEK and i.recipe.category == 'main')
    old_recipe = target.recipe_id
    replacement = next(r for r in RecipeService(db).list_recipes() if r.category == 'main' and r.id != old_recipe)
    result = await call(toolset, 'ogun_degistir', tarih=WEEK.isoformat(), yeni_tarif=replacement.name, gerekce='Onaylı menüyü düzenle', ogun_slotu=target.meal_slot)
    assert 'Değiştirildi' in result
    assert session.state == SessionState.AWAITING_APPROVAL
    assert session.published_at is None
    assert session.meal_plan.status == 'draft'
    assert any(i['recipe_id'] == old_recipe for i in session.context['previous_final']['meals'])
    MealPlannerService(db, settings).approve(session)
    from app.workflow import WeeklyWorkflowService
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    notifier = SimpleNamespace(send_message=AsyncMock())
    assert await WeeklyWorkflowService(db, settings, notifier).publish_final(session)
    assert notifier.send_message.await_count > 0
