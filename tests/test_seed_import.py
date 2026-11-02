"""Sohbette seçilen 2–6 Kasım menüsünün uygulamaya bir kez yüklenmesi."""
from __future__ import annotations

import json
from datetime import date, timedelta

import app.seed_import as seed_import
from app.db.models import MealPlan, MealPlanItem, SessionState, WeeklyPlanningSession
from app.memory.rules import validate_session
from app.planner.dates import week_end
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService
from app.shopping.service import ShoppingListService

SEED = json.loads((seed_import.SEED_DIR / "menu-2026-11-02.json").read_text(encoding="utf-8"))
WEEK = date(2026, 11, 2)


def existing_draft(db):
    service = RecipeService(db)
    taco = service.upsert_recipe(RecipeInput(name="Chicken Caesar Smash Taco", category="main",
                                             ingredients=[IngredientInput(name="tavuk", quantity=500, unit="g")]))
    session = WeeklyPlanningSession(week_start=WEEK, week_end=week_end(WEEK), state=SessionState.AWAITING_APPROVAL)
    db.add(session)
    db.flush()
    plan = MealPlan(session=session, status="draft")
    db.add(plan)
    db.flush()
    for day in range(7):
        plan.items.append(MealPlanItem(date=WEEK + timedelta(days=day), meal_slot="dinner_main", recipe_id=taco.id))
    plan.items.append(MealPlanItem(date=WEEK, meal_slot="hafta_meze_1", recipe_id=taco.id))
    db.commit()
    return session


def test_menu_recipes_and_shopping_list_are_loaded(db, settings, tmp_path):
    session = existing_draft(db)

    summary = seed_import.apply_seed(db, settings.model_copy(update={"data_dir": tmp_path}), SEED)

    assert "16 tarif" in summary and "onaylı" in summary and "uyarı" not in summary
    db.refresh(session)
    assert session.state == SessionState.APPROVED
    items = session.meal_plan.items
    by_day = {}
    for item in items:
        by_day.setdefault(item.date, []).append(item.recipe.name)
    assert by_day[WEEK] [0:1] and "Ballı-Soyalı Susamlı Fırın Tavuk" in by_day[WEEK]
    assert by_day[WEEK + timedelta(days=4)] == ["Dana Fajita Dürüm", "Meksika Usulü Mısır Salatası (Esquites)"]
    # Hafta sonu PDF'teki menüde yok: boşaltılır ki alışveriş listesi PDF'le aynı olsun.
    assert WEEK + timedelta(days=5) not in by_day and WEEK + timedelta(days=6) not in by_day
    mezes = sorted((i.meal_slot, i.recipe.name) for i in items if i.meal_slot.startswith("hafta_"))
    assert [name for _, name in mezes] == SEED["mezeler"]
    for item in items:
        if item.recipe.name in {r["ad"] for r in SEED["tarifler"]}:
            assert item.recipe.ingredients and item.recipe.instructions
            assert item.recipe.nutrition and item.recipe.nutrition.calories_kcal
    validate_session(db, session, settings)  # ana yemekler gerçekten ana yemek
    shopping = {i.name for i in ShoppingListService(db, settings).generate(session.meal_plan)}
    assert {"mezgit fileto", "hindi göğsü (ince dilim)", "süzme yoğurt"} & shopping


def test_seed_is_applied_only_once(db, settings, tmp_path, monkeypatch):
    # Gelecek bir haftaya kaydırılmış kopya: tarih geçtiği için atlanmasın.
    shift = timedelta(weeks=520)
    data = dict(SEED, id="deneme", hafta_baslangic=(WEEK + shift).isoformat(),
                gunler={(date.fromisoformat(d) + shift).isoformat(): m for d, m in SEED["gunler"].items()}, bos_gunler=[])
    seeds = tmp_path / "seed"
    seeds.mkdir()
    (seeds / "deneme.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(seed_import, "SEED_DIR", seeds)
    configured = settings.model_copy(update={"data_dir": tmp_path / "data"})

    class Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    assert len(seed_import.apply_pending(configured, Factory())) == 1
    assert seed_import.apply_pending(configured, Factory()) == []
    assert json.loads((tmp_path / "data" / "ice_aktarilanlar.json").read_text()) == ["deneme"]


def test_menu_follows_the_house_bans(db, settings, tmp_path):
    """Kullanıcının kalıcı yasakları: zencefil, zerdeçal, somon, zahter, kabak, acı."""
    from app.memory.preferences import PreferenceService
    from app.memory.rules import MealRules

    for ban in ("zencefil kullanma", "zerdeçal kullanma", "somon kullanma", "zahter kullanma", "kabak kullanma", "acı kullanma"):
        PreferenceService(db).add(ban)
    fix = json.loads((seed_import.SEED_DIR / "menu-2026-11-02-kurallar.json").read_text(encoding="utf-8"))
    summary = seed_import.apply_seed(db, settings.model_copy(update={"data_dir": tmp_path}), fix)
    assert "16 tarif güncellendi" in summary
    rules = MealRules.from_db(db)
    assert rules.excluded, "yasaklar okunamadı"
    service = RecipeService(db)
    for row in fix["tarifler"]:
        assert not rules.excludes(service.find_recipe(row["ad"])), row["ad"]
    assert db.query(WeeklyPlanningSession).count() == 0  # plana dokunmaz
