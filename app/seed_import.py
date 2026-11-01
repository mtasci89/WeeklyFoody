"""Depodaki hazır menüleri sunucuya bir kez yüklemek (app/seed/*.json).

Kullanıcı Google araması kotadayken menüyü sohbette Claude'la seçti ve "menüyü,
tarifleri ve alışveriş listesini uygulamaya yükle" dedi. Canlı sunucuya buradan
erişim yok; menü depoya dosya olarak eklenir, telefondaki "Sunucuyu güncelle"
sonrası açılışta bir kez uygulanır. Uygulanan dosyalar data/ice_aktarilanlar.json
içinde tutulur; aynı dosya ikinci kez uygulanmaz.

Yükleme: tarifler (malzemeler, hazırlanış, tahmini kalori) kütüphaneye yazılır;
o haftanın planında dosyada geçen günler ve haftalık mezeler değiştirilir,
`bos_gunler` boşaltılır, diğer günler korunur; `onayla` doğruysa menü onaylı olur. Kullanıcı
menüyü kendisi seçtiği için ev kurallarına aykırılık onayı durdurmaz, günlüğe yazılır.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent / "seed"
NUTRITION_SOURCE = "Foody: tarif malzemelerinden tahmin"


def _applied_path(settings) -> Path:
    return Path(settings.data_dir) / "ice_aktarilanlar.json"


def _applied(settings) -> set[str]:
    try:
        return set(json.loads(_applied_path(settings).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _mark(settings, seed_id: str) -> None:
    path = _applied_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(_applied(settings) | {seed_id}), ensure_ascii=False), encoding="utf-8")


def apply_seed(db, settings, data: dict) -> str:
    """Tek bir menü dosyasını uygular; kısa bir özet döndürür."""
    from app.db.models import MealPlan, MealPlanItem, SessionState, WeeklyPlanningSession
    from app.memory.rules import RuleViolation, validate_session
    from app.planner.dates import week_end
    from app.recipes.importer import RecipeInput
    from app.recipes.ingredient_lines import parse_ingredient
    from app.recipes.service import RecipeService

    service = RecipeService(db)
    recipes = {}
    for row in data["tarifler"]:
        values = dict(
            name=row["ad"], category=row["kategori"], meal_type=settings.meal_slots[0] if settings.meal_slots else "dinner",
            cuisine=row.get("mutfak"), servings=int(row.get("porsiyon") or 4),
            ingredients=[parse_ingredient(line) for line in row["malzemeler"]],
            instructions=row["hazirlanis"], protein_type=row.get("protein"), vegetarian=bool(row.get("vejetaryen")),
            notes=row.get("not"), tags=["haftalik-menu", data["id"]], status="approved",
        )
        if row.get("kcal") is not None or row.get("protein_g") is not None:
            values["nutrition"] = {"calories_kcal": row.get("kcal"), "protein_g": row.get("protein_g"),
                                   "source": NUTRITION_SOURCE, "estimated": True}
        recipes[row["ad"]] = service.upsert_recipe(RecipeInput(**values), commit=False)

    week_start = date.fromisoformat(data["hafta_baslangic"])
    session = db.query(WeeklyPlanningSession).filter(WeeklyPlanningSession.week_start == week_start).one_or_none()
    if session is None:
        session = WeeklyPlanningSession(week_start=week_start, week_end=week_end(week_start),
                                        state=SessionState.AWAITING_APPROVAL)
        db.add(session)
        db.flush()
    if session.meal_plan is None:
        session.meal_plan = MealPlan(session=session, status="draft")
        db.flush()
    plan = session.meal_plan
    # Dosyadaki günler değiştirilir; `bos_gunler` boşaltılır (dışarıda/plansız); diğerleri korunur.
    days = {date.fromisoformat(d) for d in [*data["gunler"], *data.get("bos_gunler", [])]}
    from app.config import is_weekly_slot
    replace_weekly = bool(data.get("mezeler"))
    for item in list(plan.items):
        if item.date in days and not is_weekly_slot(item.meal_slot) or (replace_weekly and is_weekly_slot(item.meal_slot)):
            plan.items.remove(item)
    db.flush()
    for day_text, meals in data["gunler"].items():
        for meal in meals:
            plan.items.append(MealPlanItem(date=date.fromisoformat(day_text), meal_slot=meal["slot"],
                                           recipe=recipes[meal["tarif"]]))
    for index, name in enumerate(data.get("mezeler") or [], 1):
        plan.items.append(MealPlanItem(date=week_start, meal_slot=f"hafta_meze_{index}", recipe=recipes[name]))
    session.draft_version = (session.draft_version or 1) + 1
    db.flush()
    note = ""
    if data.get("onayla"):
        try:
            validate_session(db, session, settings)
        except RuleViolation as error:
            note = f" (ev kuralı uyarısı: {error})"
            logger.warning("seed_rule_warning id=%s detail=%s", data["id"], error)
        session.state = SessionState.APPROVED
        plan.status = "final"
    else:
        session.state = SessionState.AWAITING_APPROVAL
    db.commit()
    summary = f"{data['id']}: {len(recipes)} tarif, {sum(len(m) for m in data['gunler'].values())} öğün, " \
              f"{len(data.get('mezeler') or [])} meze; {'onaylı' if data.get('onayla') else 'taslak'}{note}"
    logger.info("seed_applied %s", summary)
    return summary


def apply_pending(settings, session_factory) -> list[str]:
    """Henüz uygulanmamış menü dosyalarını uygular. Hata sunucuyu durdurmaz."""
    done = _applied(settings)
    results = []
    for path in sorted(SEED_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("seed_unreadable path=%s", path.name)
            continue
        if data.get("id") in done:
            continue
        # Geçmiş haftanın menüsünü yeni kurulumda yeniden yazma.
        if date.fromisoformat(data["hafta_baslangic"]) + timedelta(days=7) < date.today():
            _mark(settings, data["id"])
            continue
        try:
            with session_factory() as db:
                results.append(apply_seed(db, settings, data))
            _mark(settings, data["id"])
        except Exception:
            logger.exception("seed_failed id=%s", data.get("id"))
    return results
