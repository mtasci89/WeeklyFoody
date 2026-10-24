from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from datetime import date, timedelta
from typing import Literal

from anthropic import beta_async_tool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import WEEKLY_BASE, Settings, base_meal_slot, course_role, is_weekly_slot
from app.db.models import (
    MealPlanItem,
    PantryItem,
    Recipe,
    RecipeStatus,
    SessionState,
    WeeklyPlanningSession,
)
from app.formatting import course_label
from app.memory.feedback import FeedbackService
from app.memory.preferences import PreferenceService
from app.memory.rules import MealRules, RuleViolation
from app.recipes.nutrition import NutritionInput, nutrition_text, save_nutrition
from app.db.models import MealPlan
from app.planner.candidate_selector import CandidateSelector
from app.planner.dates import TR_DAY_NAMES, next_week_start, this_week_start, week_dates, week_end
from app.planner.scorer import CandidateScorer
from app.planner.service import MealPlannerService, allowed_categories_for_role
from app.agent.rules import HouseRules
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService, normalize_name
from app.shopping.service import ShoppingListService
from app.shopping.units import format_shopping_quantity, to_base

logger = logging.getLogger(__name__)

# NOT: Arac imzalarinda tip takma adi (HaftaSecimi gibi) KULLANMA. Araclar
# closure oldugu icin SDK'nin sema ureticisi modul seviyesindeki takma adi
# cozemiyor ve NameError atiyor; Literal'i imzaya inline yazmak gerekiyor.
SessionFactory = Callable[[], Session]


def render_plan(session: WeeklyPlanningSession | None) -> str:
    """Modele verilecek sade plan metni (kullaniciya giden bicim degil)."""
    if session is None:
        return "Bu hafta için kayıtlı plan yok."
    if not session.meal_plan or not session.meal_plan.items:
        return f"{session.week_start} haftası için oturum var ama henüz öğün yok (durum: {session.state.value})."
    lines = [
        f"Hafta: {session.week_start} - {session.week_end} (durum: {session.state.value}, versiyon: {session.draft_version})"
    ]
    by_day: dict[date, list[MealPlanItem]] = {}
    weekly = []
    for item in sorted(session.meal_plan.items, key=lambda i: (i.date, i.meal_slot)):
        if is_weekly_slot(item.meal_slot):
            weekly.append(item)
        else:
            by_day.setdefault(item.date, []).append(item)
    sections = [(f"{day.isoformat()} {TR_DAY_NAMES[day.weekday()]}:", items) for day, items in by_day.items()]
    if weekly:
        sections.append(("HAFTANIN MEZELERİ (tarih=HAFTA, günlere bağlı değil):", weekly))
    for title, items in sections:
        lines.append(f"\n{title}")
        for item in items:
            servings = f", {item.servings} kişi" if item.servings else ""
            changed = " [admin değiştirdi]" if item.admin_changed else ""
            if item.recipe.status == RecipeStatus.CANDIDATE:
                changed += " [YENİ: aday tarif, kütüphanede değil]"
            lines.append(
                f"  slot={item.meal_slot} ({course_label(item.meal_slot)}): "
                f"{item.recipe.name} [kategori={item.recipe.category}{servings}; {nutrition_text(item.recipe)}]{changed}"
            )
    # Ajan kalori kuralini kontrol edebilsin diye toplamlar her zaman verilir;
    # kullaniciya giden menude ise yalnizca kural isterse gosterilir.
    from app.formatting import nutrition_plan_lines

    lines.append("")
    lines.extend(nutrition_plan_lines(session, MealRules(show_calories=True), details=False))
    return "\n".join(lines)


UNITS = {
    "gr", "g", "gram", "kg", "ml", "l", "lt", "litre", "adet", "paket", "demet",
    "diş", "dis", "dal", "tutam", "su bardağı", "çay bardağı", "yemek kaşığı",
    "çay kaşığı", "tatlı kaşığı",
}


def parse_ingredient(line: str) -> IngredientInput:
    """"600 gr tavuk" -> (600, "gr", "tavuk").

    Modele tek tek malzeme satiri yazdirdigimiz icin burada talimat metni
    beklemiyoruz; eski duz metin ayristiricinin "rakam gecen her satir
    malzemedir" varsayimi burada yok.
    """
    tokens = line.strip().split()
    if not tokens:
        return IngredientInput(name=line.strip() or "bilinmeyen")
    try:
        quantity = float(tokens[0].replace(",", "."))
    except ValueError:
        return IngredientInput(name=" ".join(tokens).casefold())
    rest = tokens[1:]
    unit = None
    # Iki kelimelik birimler ("yemek kaşığı") tek kelimelilerden once denenir.
    if len(rest) >= 2 and " ".join(rest[:2]).casefold() in UNITS:
        unit, rest = " ".join(rest[:2]).casefold(), rest[2:]
    elif rest and rest[0].casefold() in UNITS:
        unit, rest = rest[0].casefold(), rest[1:]
    name = " ".join(rest).casefold().strip()
    return IngredientInput(name=name or line.strip().casefold(), quantity=quantity, unit=unit)


KNOWN_ROLES = {"main", "meze", "salad", "side", "soup"}


def selector_matches_role(db: Session, recipe: Recipe, role: str) -> bool:
    """Kategori/rol esleme kuralini tek yerden kullan."""
    return CandidateSelector(db)._matches_course_role(recipe, role)


def role_for_category(category: str | None) -> str:
    category = (category or "main").casefold()
    if category in {"main", "meze", "salad", "soup"}:
        return category
    return "side"


def _describe(recipe: Recipe) -> str:
    effort = (recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)
    parts = [f"kategori={recipe.category}", f"durum={recipe.status.value}"]
    if recipe.protein_type:
        parts.append(f"protein={recipe.protein_type}")
    if effort:
        parts.append(f"{effort} dk")
    if recipe.vegetarian:
        parts.append("vejetaryen")
    parts.append(f"{len(recipe.ingredients)} malzeme")
    parts.append(nutrition_text(recipe))
    return f"{recipe.name} ({', '.join(parts)})"


class MealAgentToolset:
    """Mevcut servis katmanini Claude araclarina baglar.

    Her arac kendi veritabani oturumunu acar; anlama isini model yapar, yazma
    isini bu deterministik fonksiyonlar yapar.
    """

    # "telegram" ya da "uygulama": cevabın nasıl yazılacağını belirler.
    channel = "telegram"

    def __init__(self, settings: Settings, session_factory: SessionFactory, estimator=None, notifier=None):
        self.settings = settings
        self.session_factory = session_factory
        # Onaylanan menuyu alicilara gonderen Telegram baglantisi; yoksa yalnizca onaylanir.
        self.notifier = notifier
        self.rules = HouseRules(session_factory)
        self.calls: list[str] = []
        # Kural kalori istiyorsa eksik degerleri tek istekte tahmin eder
        # (app.agent.nutrition.NutritionEstimator); yoksa None.
        self.estimator = estimator
        # Bu turda plani okunan/degistirilen hafta: cevabin altina sistem
        # kalori ozetini eklemek icin.
        self.touched_session_id: str | None = None

    async def _ensure_nutrition(self, db: Session, recipes) -> None:
        if self.estimator is None:
            return
        rules = MealRules.from_db(db)
        if rules.show_calories or rules.max_kcal is not None:
            await self.estimator.fill_missing(db, recipes)

    # --- yardimcilar -----------------------------------------------------

    def _resolve_session(self, db: Session, hafta: str) -> WeeklyPlanningSession | None:
        planner = MealPlannerService(db, self.settings)
        if hafta == "bu_hafta":
            return planner.this_week_session()
        if hafta == "gelecek_hafta":
            return planner.current_session()
        return planner.active_session()

    def _session_for(self, db: Session, hafta: str, tarih: str = "") -> WeeklyPlanningSession | None:
        """Tarih verildiyse o tarihi kapsayan hafta; yoksa `hafta`. Böylece
        ekranda bakılan haftanın bir günü söylendiğinde doğru plan değişir."""
        if hafta == "aktif" and tarih.strip() and tarih.strip().upper() != "HAFTA":
            try:
                day = date.fromisoformat(tarih.strip())
            except ValueError:
                day = None
            if day is not None:
                found = db.scalar(
                    select(WeeklyPlanningSession).where(
                        WeeklyPlanningSession.week_start <= day, WeeklyPlanningSession.week_end >= day
                    )
                )
                if found is not None:
                    return found
        return self._resolve_session(db, hafta)

    def _clash(self, db: Session, session, day: date, slot: str, recipe, ignore=None) -> str | None:
        """Tekrar yasağı (talimata bırakılmaz): aynı ana yemek haftada bir kez;
        hiçbir yemek arka arkaya iki gün (hafta geçişi dahil). Sorun yoksa None."""
        if is_weekly_slot(slot) or not self.settings.no_repeat_meals:
            return None
        role = course_role(slot)
        items = [i for i in (session.meal_plan.items if session.meal_plan else []) if i is not ignore]
        if role == "main":
            same = next(
                (i for i in items if i.recipe_id == recipe.id and course_role(i.meal_slot) == "main"
                 and not is_weekly_slot(i.meal_slot) and i.date != day),
                None,
            )
            if same is not None:
                return (
                    f"{recipe.name} bu hafta zaten {TR_DAY_NAMES[same.date.weekday()]} günü var; "
                    "aynı ana yemek haftada bir kez olur. Başka bir yemek seç ya da yenisiyle_degistir kullan."
                )
        neighbours = db.scalars(
            select(MealPlanItem).where(
                MealPlanItem.date.in_([day - timedelta(days=1), day + timedelta(days=1)]),
                MealPlanItem.recipe_id == recipe.id,
            )
        ).all()
        for item in neighbours:
            if item is ignore or is_weekly_slot(item.meal_slot):
                continue
            return (
                f"{recipe.name} {item.date.isoformat()} ({TR_DAY_NAMES[item.date.weekday()]}) günü de var; "
                "aynı yemek arka arkaya iki gün olmaz. Başka bir yemek seç ya da yenisiyle_degistir kullan."
            )
        return None

    def _editable_session(self, db: Session, hafta: str, tarih: str = ""):
        """Değiştirilebilir plan oturumu ya da kullanıcıya söylenecek sorun."""
        session = self._session_for(db, hafta, tarih)
        if session is None or not session.meal_plan:
            return None, "Bu hafta için kayıtlı plan yok. Önce plan_hazirla + plan_kaydet ile kur."
        if session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
            return None, "Bu plan onaylanmış/yayınlanmış, değiştirilemez."
        return session, None

    def plan_summary(self) -> str:
        with self.session_factory() as db:
            return render_plan(self._resolve_session(db, "aktif"))

    def ambient_context(self) -> tuple[list[str], list[str], list[str]]:
        with self.session_factory() as db:
            prefs = PreferenceService(db)
            pantry = [p.ingredient_name for p in db.scalars(select(PantryItem).order_by(PantryItem.ingredient_name))]
            status = MealRules.from_db(db).summary()
            return prefs.hard_rules() + status, prefs.soft_rules(), pantry

    # --- araclar ---------------------------------------------------------

    def build(self) -> list:
        toolset = self

        @beta_async_tool
        async def plani_getir(hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif") -> str:
            """Haftalık yemek planını gün gün döndürür.

            Args:
                hafta: "aktif" (onay bekleyen taslak varsa o, yoksa içinde
                    bulunduğumuz hafta), "bu_hafta" (şu an yediğimiz hafta) veya
                    "gelecek_hafta" (planlanan hafta).
            """
            toolset.calls.append(f"plani_getir(hafta={hafta})")
            with toolset.session_factory() as db:
                session = toolset._resolve_session(db, hafta)
                if session is not None and session.meal_plan is not None:
                    await toolset._ensure_nutrition(db, [i.recipe for i in session.meal_plan.items])
                    toolset.touched_session_id = session.id
                return render_plan(session)

        @beta_async_tool
        async def tarif_ara(sorgu: str = "", kategori: str = "", limit: int = 8) -> str:
            """Tarif kütüphanesinde arama yapar. Menüye koyacağın her tarifi
            önce buradan doğrula.

            Args:
                sorgu: Tarif adında veya malzemelerinde aranacak kelime. Boş
                    bırakılırsa kategoriye uyan tarifler listelenir.
                kategori: Daraltmak için: main, meze, salad, side, soup.
                limit: En fazla kaç sonuç dönsün.
            """
            toolset.calls.append(f"tarif_ara(sorgu={sorgu!r}, kategori={kategori!r})")
            needle = sorgu.casefold().strip()
            with toolset.session_factory() as db:
                stmt = select(Recipe).where(Recipe.status != RecipeStatus.INACTIVE).order_by(Recipe.name)
                if kategori:
                    stmt = stmt.where(Recipe.category == kategori.casefold().strip())
                hits = []
                for recipe in db.scalars(stmt):
                    if needle:
                        haystack = " ".join(
                            [
                                recipe.name,
                                recipe.protein_type or "",
                                " ".join(recipe.tags or []),
                                " ".join(ri.ingredient.name for ri in recipe.ingredients),
                            ]
                        ).casefold()
                        if needle not in haystack:
                            continue
                    hits.append(_describe(recipe))
                    if len(hits) >= max(1, min(limit, 30)):
                        break
                if not hits:
                    return f"'{sorgu}' için kütüphanede tarif bulunamadı. Kullanıcıya tarifi eklemeyi teklif edebilirsin."
                return "\n".join(f"- {line}" for line in hits)

        @beta_async_tool
        async def tarif_detay(tarif_adi: str, kisi: int = 0) -> str:
            """Bir tarifin malzemelerini ve hazırlanışını döndürür. Kullanıcı
            tarif istediğinde bunu çağır ve malzemeleri miktarlarıyla aynen ver.

            Args:
                tarif_adi: Tarifin tam adı.
                kisi: Kaç kişilik olsun; 0 ise menüdeki kişi sayısı (varsayılan
                    porsiyon) kullanılır. Miktarlar buna göre ölçeklenir.
            """
            toolset.calls.append(f"tarif_detay({tarif_adi!r}, kisi={kisi})")
            with toolset.session_factory() as db:
                recipe = RecipeService(db).find_recipe(tarif_adi)
                if not recipe:
                    return f"'{tarif_adi}' adlı tarif bulunamadı. tarif_ara ile doğru adı arayabilirsin."
                people = kisi if kisi > 0 else toolset.settings.default_servings
                scale = people / recipe.servings if recipe.servings else 1
                lines = [_describe(recipe), f"{people} kişi için malzemeler (tarifin aslı {recipe.servings} porsiyon):"]
                for ing in recipe.ingredients:
                    if ing.quantity is None:
                        qty = "kararınca"
                    else:
                        base = to_base(ing.quantity * scale, ing.unit)
                        qty = format_shopping_quantity(base.quantity, base.unit)
                    lines.append(f"  - {qty} {ing.ingredient.name}")
                lines.append(f"Hazırlanış: {recipe.instructions or 'kayıtlı değil'}")
                return "\n".join(lines)

        @beta_async_tool
        async def ogun_degistir(
            tarih: str,
            yeni_tarif: str,
            gerekce: str,
            ogun_slotu: str = "",
            hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif",
        ) -> str:
            """Plandaki bir öğünü başka bir tarifle değiştirir. Onaylanmış veya
            yayınlanmış planlar değiştirilemez.

            Args:
                tarih: Değişecek günün ISO tarihi, örn. 2026-10-20. Haftalık
                    meze listesindeki bir mezeyse "HAFTA".
                yeni_tarif: Yerine konacak tarifin adı. Kütüphanede (onaylı ya da
                    aday) bulunmalı; yeni bir yemekse önce `tarif_ekle` ile kaydet.
                gerekce: Bu değişikliği neden yaptığın. Kaydedilir ve ileride
                    menü önerilirken hatırlanır.
                ogun_slotu: Günde birden fazla öğün varsa hangisi, örn.
                    dinner_main. Boş bırakılırsa yeni tarifin kategorisine uyan
                    öğün seçilir.
                hafta: Hangi haftanın planı. Kullanıcı ekranda baktığı haftayı
                    ya da "bu hafta"/"gelecek hafta" diye belirtirse ona uy.
            """
            toolset.calls.append(f"ogun_degistir(tarih={tarih}, yeni_tarif={yeni_tarif!r}, slot={ogun_slotu!r}, hafta={hafta})")
            weekly_target = tarih.strip().upper() == "HAFTA"
            target = None
            if not weekly_target:
                try:
                    target = date.fromisoformat(tarih.strip())
                except ValueError:
                    return f"'{tarih}' geçerli bir ISO tarih değil. 2026-10-20 biçiminde ya da HAFTA ver."
            with toolset.session_factory() as db:
                session = toolset._session_for(db, hafta, tarih)
                if not session or not session.meal_plan:
                    return "Değiştirilecek aktif bir plan yok."
                if session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
                    return (
                        "Bu plan onaylanmış/yayınlanmış durumda, değiştirilemez. "
                        "Kullanıcıya /regenerate ile yeni taslak oluşturabileceğini söyle."
                    )
                replacement = RecipeService(db).find_recipe(yeni_tarif)
                if not replacement:
                    return (
                        f"'{yeni_tarif}' kütüphanede yok. tarif_ara ile doğru adı bul; yeni bir yemekse "
                        "önce tarif_ekle ile kaydet, sonra tekrar çağır."
                    )
                if weekly_target:
                    day_items = [i for i in session.meal_plan.items if is_weekly_slot(i.meal_slot)]
                    target = session.week_start
                    if not day_items:
                        return "Bu planda haftalık meze listesi yok. Eklemek için ogun_ekle(tarih=\"HAFTA\") kullan."
                else:
                    day_items = [
                        i for i in session.meal_plan.items if i.date == target and not is_weekly_slot(i.meal_slot)
                    ]
                if not day_items:
                    return f"{tarih} planda yok. Plan {session.week_start} - {session.week_end} arasını kapsıyor."
                if ogun_slotu:
                    chosen = next((i for i in day_items if i.meal_slot == ogun_slotu.strip()), None)
                    if not chosen:
                        opts = ", ".join(i.meal_slot for i in day_items)
                        return f"'{ogun_slotu}' o günde yok. Mevcut slotlar: {opts}"
                else:
                    same_category = [i for i in day_items if i.recipe.category == replacement.category]
                    if len(same_category) == 1:
                        chosen = same_category[0]
                    elif len(day_items) == 1:
                        chosen = day_items[0]
                    else:
                        opts = "; ".join(
                            f"{i.meal_slot} = {i.recipe.name} ({i.recipe.category})" for i in day_items
                        )
                        return (
                            f"{tarih} günü birden fazla öğün var, hangisini değiştireceğim belirsiz. "
                            f"Seçenekler: {opts}. ogun_slotu vererek tekrar çağır veya kullanıcıya sor."
                        )
                if chosen.recipe_id == replacement.id:
                    return f"{tarih} {chosen.meal_slot} zaten {replacement.name}. Değişiklik gerekmedi."
                if replacement.status == RecipeStatus.INACTIVE:
                    return "Bu tarif pasifleştirilmiş, menüye konamaz."
                clash = toolset._clash(db, session, chosen.date, chosen.meal_slot, replacement, ignore=chosen)
                if clash:
                    return f"Değişiklik kaydedilmedi: {clash}"
                proposed = [(i.date, i.meal_slot, replacement if i is chosen else i.recipe) for i in session.meal_plan.items]
                await toolset._ensure_nutrition(db, [recipe for _, _, recipe in proposed])
                try:
                    MealRules.from_db(db).validate(proposed)
                except RuleViolation as error:
                    return f"Değişiklik kaydedilmedi: {error}"
                original_id = chosen.recipe_id
                original_name = chosen.recipe.name
                chosen.original_recipe_id = chosen.original_recipe_id or original_id
                chosen.recipe_id = replacement.id
                chosen.recipe = replacement
                chosen.admin_changed = True
                chosen.change_reason = gerekce
                FeedbackService(db).record(
                    gerekce,
                    session_id=session.id,
                    original_recipe_id=original_id,
                    replacement_recipe_id=replacement.id,
                    context={"date": target.isoformat(), "meal_slot": chosen.meal_slot, "source": "agent"},
                )
                session.state = SessionState.AWAITING_APPROVAL
                session.draft_version += 1
                db.commit()
                toolset.touched_session_id = session.id
                logger.info(
                    "agent_meal_swapped session_id=%s date=%s slot=%s", session.id, target, chosen.meal_slot
                )
                return (
                    f"Değiştirildi: {tarih} {chosen.meal_slot} "
                    f"{original_name} -> {replacement.name}. Gerekçe kaydedildi."
                )

        @beta_async_tool
        async def ogun_ekle(
            tarih: str,
            tarif: str,
            gerekce: str = "",
            rol: Literal["", "main", "meze", "salad", "side", "soup"] = "",
            hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif",
        ) -> str:
            """Plana bir yemek EKLER; mevcut öğünlere dokunmaz. Bütün haftayı
            yeniden yazmadan "Salı'ya çorba ekle", "meze listesine Atom ekle"
            gibi istekler için. Birkaç güne eklenecekse her gün için ayrı
            (paralel) çağır.

            Args:
                tarih: Günün ISO tarihi (2026-10-20) ya da haftalık meze
                    listesi için "HAFTA".
                tarif: Eklenecek tarifin adı (kütüphanede ya da aday). Yeni bir
                    yemekse önce tarif_ekle ile kaydet.
                gerekce: Neden eklendiği, kısaca.
                rol: Boşsa tarifin kategorisinden çıkarılır.
                hafta: Hangi haftanın planı.
            """
            toolset.calls.append(f"ogun_ekle(tarih={tarih}, tarif={tarif!r}, hafta={hafta})")
            with toolset.session_factory() as db:
                session, problem = toolset._editable_session(db, hafta, tarih)
                if problem:
                    return problem
                recipe = RecipeService(db).find_recipe(tarif)
                if recipe is None:
                    return f"'{tarif}' kütüphanede yok. tarif_ara ile adı doğrula; yeni bir yemekse önce tarif_ekle ile kaydet."
                role = rol or role_for_category(recipe.category)
                rules = MealRules.from_db(db)
                weekly_mode = rules.weekly_meze_target(toolset.settings) > 0
                weekly = tarih.strip().upper() == "HAFTA" or (weekly_mode and role == "meze")
                items = list(session.meal_plan.items) if session.meal_plan else []
                note = ""
                if weekly:
                    day = session.week_start
                    if tarih.strip().upper() != "HAFTA":
                        note = " Mezeler bu evde günlere bölünmüyor; haftalık meze listesine ekledim."
                    from app.planner.mezes import next_weekly_slot

                    slot = next_weekly_slot({i.meal_slot for i in items}, "meze")
                    if any(is_weekly_slot(i.meal_slot) and i.recipe_id == recipe.id for i in items):
                        return f"{recipe.name} zaten haftanın mezelerinde."
                else:
                    try:
                        day = date.fromisoformat(tarih.strip())
                    except ValueError:
                        return f"'{tarih}' geçerli bir tarih değil. 2026-10-20 biçiminde ya da HAFTA ver."
                    if day not in week_dates(session.week_start):
                        return f"{tarih} bu planın haftasında değil ({session.week_start} - {session.week_end})."
                    base = toolset.settings.meal_slots[0] if toolset.settings.meal_slots else "dinner"
                    taken = {i.meal_slot for i in items if i.date == day}
                    if any(i.date == day and i.recipe_id == recipe.id for i in items):
                        return f"{recipe.name} o gün zaten var."
                    slot = f"{base}_{role}"
                    index = 1
                    while slot in taken:
                        index += 1
                        slot = f"{base}_{role}_{index}"
                if not weekly and not selector_matches_role(db, recipe, role):
                    return f"'{recipe.name}' ({recipe.category}) {role} rolüne uymuyor."
                if not weekly:
                    clash = toolset._clash(db, session, day, slot, recipe)
                    if clash:
                        return f"Eklenmedi: {clash}"
                proposed = [(i.date, i.meal_slot, i.recipe) for i in items] + [(day, slot, recipe)]
                await toolset._ensure_nutrition(db, [recipe])
                try:
                    rules.validate(proposed)
                except RuleViolation as error:
                    return f"Eklenmedi: {error}"
                if session.meal_plan is None:
                    session.meal_plan = MealPlan(session=session, status="draft")
                    db.flush()
                session.meal_plan.items.append(
                    MealPlanItem(date=day, meal_slot=slot, recipe_id=recipe.id, admin_changed=True,
                                 change_reason=gerekce or None)
                )
                session.state = SessionState.AWAITING_APPROVAL
                session.draft_version += 1
                db.commit()
                toolset.touched_session_id = session.id
                where = "haftanın mezelerine" if weekly else f"{tarih} ({slot})"
                logger.info("agent_meal_added session_id=%s slot=%s", session.id, slot)
                return f"Eklendi: {recipe.name} -> {where}.{note}"

        @beta_async_tool
        async def ogun_cikar(
            tarih: str,
            tarif_veya_slot: str,
            gerekce: str = "",
            hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif",
        ) -> str:
            """Plandan bir yemeği ÇIKARIR (yerine bir şey koymaz).

            Args:
                tarih: Günün ISO tarihi ya da haftalık meze listesi için "HAFTA".
                tarif_veya_slot: Çıkarılacak yemeğin adı ya da slotu.
                gerekce: Neden, kısaca.
                hafta: Hangi haftanın planı.
            """
            toolset.calls.append(f"ogun_cikar(tarih={tarih}, {tarif_veya_slot!r}, hafta={hafta})")
            with toolset.session_factory() as db:
                session, problem = toolset._editable_session(db, hafta, tarih)
                if problem:
                    return problem
                items = list(session.meal_plan.items) if session.meal_plan else []
                if tarih.strip().upper() == "HAFTA":
                    pool = [i for i in items if is_weekly_slot(i.meal_slot)]
                else:
                    try:
                        day = date.fromisoformat(tarih.strip())
                    except ValueError:
                        return f"'{tarih}' geçerli bir tarih değil. 2026-10-20 biçiminde ya da HAFTA ver."
                    pool = [i for i in items if i.date == day and not is_weekly_slot(i.meal_slot)]
                needle = normalize_name(tarif_veya_slot)
                chosen = next(
                    (i for i in pool if i.meal_slot == tarif_veya_slot.strip() or normalize_name(i.recipe.name) == needle),
                    None,
                )
                if chosen is None:
                    listed = ", ".join(f"{i.meal_slot}={i.recipe.name}" for i in pool) or "boş"
                    return f"'{tarif_veya_slot}' orada yok. Mevcut: {listed}"
                remaining = [(i.date, i.meal_slot, i.recipe) for i in items if i is not chosen]
                try:
                    MealRules.from_db(db).validate(remaining)
                except RuleViolation as error:
                    return f"Çıkarılmadı: {error}"
                name = chosen.recipe.name
                session.meal_plan.items.remove(chosen)
                if gerekce.strip():
                    FeedbackService(db).record(
                        gerekce, session_id=session.id, original_recipe_id=chosen.recipe_id,
                        context={"date": chosen.date.isoformat(), "meal_slot": chosen.meal_slot, "source": "agent"},
                    )
                session.state = SessionState.AWAITING_APPROVAL
                session.draft_version += 1
                db.commit()
                toolset.touched_session_id = session.id
                logger.info("agent_meal_removed session_id=%s", session.id)
                return f"Çıkarıldı: {name} ({tarih})."

        @beta_async_tool
        async def yenisiyle_degistir(
            tarih: str,
            ogun_slotu: str = "",
            istek: str = "",
            hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif",
        ) -> str:
            """Bir öğünü KÜTÜPHANEDE OLMAYAN, yepyeni bir yemekle değiştirir:
            kaçınılacak yemekleri (kütüphane, bu hafta, son haftalar) ve ev
            kurallarını vererek farklı mutfaklardan tarifiyle öneri üretir,
            uygun olanı aday tarif olarak kaydedip öğüne koyar.

            Kullanıcı "yeni", "farklı", "yenilikçi", "sıradışı", "başka bir şey",
            "bu olmamış" dediğinde kütüphaneden seçmek yerine BUNU kullan. Birden
            çok öğün için ayrı ayrı (paralel) çağır.

            Args:
                tarih: Günün ISO tarihi ya da haftalık meze listesi için "HAFTA".
                ogun_slotu: Hangi öğün (boşsa o günün ana yemeği).
                istek: Kullanıcının sözü, örn. "daha hafif, Asya mutfağı olsun".
                hafta: Hangi haftanın planı.
            """
            from app.agent.fresh import SCHEMA as FRESH_SCHEMA, SOURCE as FRESH_SOURCE, as_probe, build_prompt, parse_ideas

            toolset.calls.append(f"yenisiyle_degistir(tarih={tarih}, slot={ogun_slotu!r})")
            ask = getattr(toolset.estimator, "ask_json", None)
            if ask is None:
                return "Yeni tarif üretemiyorum (yapay zekâ kapalı). tarif_ekle ile tarifi kendin kaydedip ogun_degistir kullan."
            with toolset.session_factory() as db:
                session, problem = toolset._editable_session(db, hafta, tarih)
                if problem:
                    return problem
                items = list(session.meal_plan.items)
                if tarih.strip().upper() == "HAFTA":
                    pool = [i for i in items if is_weekly_slot(i.meal_slot)]
                else:
                    try:
                        day = date.fromisoformat(tarih.strip())
                    except ValueError:
                        return f"'{tarih}' geçerli bir tarih değil. 2026-10-20 biçiminde ya da HAFTA ver."
                    pool = [i for i in items if i.date == day and not is_weekly_slot(i.meal_slot)]
                if ogun_slotu.strip():
                    chosen = next((i for i in pool if i.meal_slot == ogun_slotu.strip()), None)
                else:
                    chosen = next((i for i in pool if course_role(i.meal_slot) == "main"), None) or (
                        pool[0] if len(pool) == 1 else None
                    )
                if chosen is None:
                    listed = ", ".join(f"{i.meal_slot}={i.recipe.name}" for i in pool) or "boş"
                    return f"Hangi öğün? Mevcut: {listed}. ogun_slotu ver."
                role = "meze" if is_weekly_slot(chosen.meal_slot) else course_role(chosen.meal_slot)
                slot, replacing = chosen.meal_slot, chosen.recipe.name
                cutoff = session.week_start - timedelta(weeks=4)
                recent = db.scalars(
                    select(Recipe.name).join(MealPlanItem, MealPlanItem.recipe_id == Recipe.id).where(MealPlanItem.date >= cutoff)
                ).all()
                library = [r.name for r in RecipeService(db).list_recipes(include_candidates=True)]
                avoid = list(dict.fromkeys([*(i.recipe.name for i in items), *recent, *library]))[:400]
                prefs = PreferenceService(db)
                house = [*prefs.hard_rules(), *prefs.soft_rules()]
                rules = MealRules.from_db(db)
            try:
                raw = await ask(build_prompt(role, replacing, istek, avoid, house, 3), FRESH_SCHEMA)
            except Exception as error:
                logger.exception("fresh_ideas_failed")
                return f"Yeni öneri üretilemedi: {type(error).__name__}. Biraz sonra tekrar dene ya da web_ara kullan."
            ideas = parse_ideas(raw)
            picked = None
            with toolset.session_factory() as db:
                service = RecipeService(db)
                for idea in ideas:
                    if service.find_recipe(idea["ad"], include_inactive=True) is not None:
                        continue
                    if rules.excludes(as_probe(idea)):
                        continue
                    category = role if role in ("main", "meze", "salad", "soup") else "side"
                    service.upsert_recipe(
                        RecipeInput(
                            name=idea["ad"],
                            category=category,
                            meal_type="dinner",
                            ingredients=[parse_ingredient(line) for line in idea["malzemeler"]],
                            instructions=str(idea.get("hazirlanis") or "").strip() or None,
                            servings=max(1, int(idea.get("porsiyon") or 4)),
                            prep_minutes=int(idea.get("hazirlik_dakika") or 0) or None,
                            cook_minutes=int(idea.get("pisirme_dakika") or 0) or None,
                            protein_type=str(idea.get("protein") or "").strip().casefold() or None,
                            vegetarian=bool(idea.get("vejetaryen")),
                            source=FRESH_SOURCE,
                            tags=["agent-eklendi", "yeni-oneri"],
                            status="candidate",
                        )
                    )
                    picked = idea
                    break
            if picked is None:
                return (
                    "Uygun yeni öneri çıkmadı (öneriler ya kütüphanede vardı ya da ev kuralına takıldı). "
                    "Bir kez daha dene ya da web_ara ile ara."
                )
            logger.info("fresh_dish_added role=%s", role)
            result = await ogun_degistir.call(
                {"tarih": tarih, "yeni_tarif": picked["ad"], "ogun_slotu": slot, "hafta": hafta,
                 "gerekce": f"Yeni bir şey istendi ({replacing} yerine): {istek or 'daha yenilikçi'}"}
            )
            others = [i["ad"] for i in ideas if i is not picked]
            extra = f" Diğer fikirler (kaydedilmedi): {', '.join(others)}." if others else ""
            return (
                f"{result}\nYeni tarif kaydedildi: {picked['ad']}"
                f"{' (' + picked['mutfak'] + ')' if picked.get('mutfak') else ''}"
                f"{' — ' + picked['neden'] if picked.get('neden') else ''}.{extra} "
                "Kullanıcı beğenirse tarif_onayla ile kalıcı listeye alınır."
            )

        @beta_async_tool
        async def alisveris_listesi(hafta: Literal["aktif", "bu_hafta", "gelecek_hafta"] = "aktif") -> str:
            """Bir haftanın planından toplu alışveriş listesi çıkarır.

            Args:
                hafta: "aktif", "bu_hafta" veya "gelecek_hafta".
            """
            toolset.calls.append(f"alisveris_listesi(hafta={hafta})")
            with toolset.session_factory() as db:
                session = toolset._resolve_session(db, hafta)
                if not session or not session.meal_plan or not session.meal_plan.items:
                    return "O hafta için plan yok, liste çıkaramam."
                service = ShoppingListService(db, toolset.settings)
                items = service.generate(session.meal_plan)
                if not items:
                    return "Listede kalem yok (her şey kilerde olabilir)."
                lines = [f"{session.week_start} - {session.week_end} haftası için:"]
                for item in items:
                    lines.append(f"  - [{item.category}] {item.format()}")
                return "\n".join(lines)

        @beta_async_tool
        async def gecmis_getir(hafta_sayisi: int = 6) -> str:
            """Son haftalarda yapılan yemekleri, en yeniden eskiye döndürür.
            "Geçen ay ne yemiştik", "bunu en son ne zaman yaptık" gibi
            sorularda ve tekrardan kaçınmak için kullan.

            Args:
                hafta_sayisi: Kaç hafta geriye bakılsın.
            """
            toolset.calls.append(f"gecmis_getir(hafta_sayisi={hafta_sayisi})")
            weeks = max(1, min(hafta_sayisi, 26))
            with toolset.session_factory() as db:
                cutoff = this_week_start(timezone=toolset.settings.timezone) - timedelta(weeks=weeks)
                rows = db.scalars(
                    select(MealPlanItem)
                    .join(MealPlanItem.plan)
                    .join(WeeklyPlanningSession)
                    .where(
                        WeeklyPlanningSession.week_start >= cutoff,
                        WeeklyPlanningSession.state.in_([SessionState.APPROVED, SessionState.PUBLISHED]),
                    )
                    .order_by(MealPlanItem.date.desc())
                ).all()
                if not rows:
                    return f"Son {weeks} haftada onaylanmış plan kaydı yok."
                lines = []
                for row in rows[:80]:
                    lines.append(
                        f"  {row.date.isoformat()} {TR_DAY_NAMES[row.date.weekday()]} "
                        f"{course_role(row.meal_slot)}: {row.recipe.name}"
                    )
                return f"Son {weeks} haftada yapılanlar (yeniden eskiye):\n" + "\n".join(lines)

        @beta_async_tool
        async def kurallari_goster() -> str:
            """Ev kurallarını ve sistemin hangisini otomatik denetlediğini listeler."""
            toolset.calls.append("kurallari_goster()")
            rules = toolset.rules.active()
            if not rules:
                return "Henüz ev kuralı yok."
            listed = "\n".join(f"{i}. {rule}" for i, rule in enumerate(rules, 1))
            return f"{len(rules)} ev kuralı:\n{listed}\n\n" + "\n".join(toolset.rules.summary())

        @beta_async_tool
        async def kural_ekle(kural: str) -> str:
            """Ev kurallarına kalıcı bir kural ekler; bundan sonraki her
            planlamada uygulanır. Kullanıcı kalıcı bir şey söylediğinde
            ("bundan sonra", "hep", "asla", "her zaman") sormadan ekle ve
            eklediğini söyle. Sadece bu haftaya özel isteklerde ekleme.

            Args:
                kural: Kuralın tek cümlelik, net Türkçe hali. Örn: "Balık
                    kullanma", "Her öğünde 3 farklı yemek olsun", "Kişi başı
                    öğün en fazla 1000 kcal", "Protein ağırlıklı olsun".
                    Kesin olmayan bir eğilimse başına "Tercih: " yaz.
            """
            toolset.calls.append(f"kural_ekle({kural!r})")
            added, detail = toolset.rules.add(kural)
            if not added:
                return f"Kural eklenmedi: {detail}"
            logger.info("agent_rule_added")
            return (
                f"Kural eklendi, bundan sonra her planlamada uygulanacak: {detail}\n"
                + "\n".join(toolset.rules.summary())
            )

        @beta_async_tool
        async def kural_sil(ifade: str) -> str:
            """Ev kurallarından bir kuralı siler.

            Args:
                ifade: Silinecek kuralı tanımlayan kelime ya da kuralın kendisi,
                    örn. "balık".
            """
            toolset.calls.append(f"kural_sil({ifade!r})")
            matches = toolset.rules.matching(ifade)
            if not matches:
                return f"'{ifade}' geçen bir kural yok. kurallari_goster ile listeye bakabilirsin."
            if len(matches) > 1:
                listed = "\n".join(f"- {m}" for m in matches)
                return f"'{ifade}' birden fazla kuralda geçiyor, hangisini sileyim?\n{listed}"
            toolset.rules.remove(matches[0])
            logger.info("agent_rule_removed")
            return f"Kural silindi: {matches[0]}"

        @beta_async_tool
        async def besin_degeri_kaydet(degerler: list[str]) -> str:
            """Tariflerin KİŞİ BAŞI (1 porsiyon) tahmini kalori ve proteinini
            kaydeder; bir kez kaydedilen değer sonraki planlarda tekrar
            kullanılır. Malzemelere ve porsiyon sayısına bakarak tahmin et
            (gerekirse önce tarif_detay). Birden çok tarifi tek çağrıda ver.

            Args:
                degerler: Her satır "TARİF ADI|KALORİ|PROTEİN_GRAM". Örn:
                    "Fırında Tavuk|520|42". Protein bilinmiyorsa
                    "Fırında Tavuk|520" yazabilirsin.
            """
            toolset.calls.append(f"besin_degeri_kaydet({len(degerler)} tarif)")
            saved, problems = [], []
            with toolset.session_factory() as db:
                service = RecipeService(db)
                for raw in degerler:
                    parts = [part.strip() for part in raw.split("|")]
                    if len(parts) not in (2, 3):
                        problems.append(f"'{raw}' biçimi yanlış (TARİF|KALORİ|PROTEİN)")
                        continue
                    recipe = service.find_recipe(parts[0], include_inactive=True)
                    if recipe is None:
                        problems.append(f"'{parts[0]}' kütüphanede yok")
                        continue
                    if recipe.nutrition is not None and not recipe.nutrition.estimated:
                        problems.append(f"'{recipe.name}' için kullanıcının girdiği değer var, üzerine yazmadım")
                        continue
                    try:
                        kcal = round(float(parts[1].replace(",", ".")))
                        protein = round(float(parts[2].replace(",", "."))) if len(parts) == 3 and parts[2] else None
                    except ValueError:
                        problems.append(f"'{raw}' içinde sayı okunamadı")
                        continue
                    if not 20 <= kcal <= 3000 or (protein is not None and not 0 <= protein <= 250):
                        problems.append(f"'{recipe.name}' için değerler makul aralıkta değil ({kcal} kcal, {protein} g)")
                        continue
                    save_nutrition(
                        db,
                        recipe,
                        NutritionInput(
                            calories_kcal=kcal,
                            protein_g=protein,
                            source="ajan tahmini (malzemelerden)",
                            estimated=True,
                        ),
                    )
                    saved.append(f"{recipe.name}: ~{kcal} kcal" + (f", {protein} g protein" if protein is not None else ""))
                db.commit()
            report = []
            if saved:
                report.append(f"{len(saved)} tarifin besin değeri tahmini olarak kaydedildi:")
                report += [f"  - {line}" for line in saved]
            if problems:
                report.append("Kaydedilemeyenler:")
                report += [f"  - {line}" for line in problems]
            return "\n".join(report) or "Hiçbir şey kaydedilmedi."

        @beta_async_tool
        async def plan_hazirla(
            hafta: Literal["gelecek_hafta", "bu_hafta"] = "gelecek_hafta",
        ) -> str:
            """Yeni bir haftalık plan kurmak için hazırlık bilgisini verir:
            haftanın günleri, ÖNERİLEN gün şekli ve her ROL için PUANLANMIŞ
            aday havuzu. Plan kurmadan önce bunu çağır; seçimlerini bu
            havuzdan yap.

            Önerilen şekil bağlayıcı değildir. Kullanıcı "tek meze olsun",
            "çorba ekle", "cumartesi sadece ana yemek" derse ona göre kurarsın.

            Puan; yemeğin en son ne zaman yapıldığını, kaç kez reddedildiğini,
            protein tekrarını ve hafta içi/sonu hazırlık süresini birleştirir.
            Yüksek puan "bu hafta için daha uygun" demektir, ama bağlayıcı
            değil: gerekçeni yazdığın sürece listeden aşağıdan da seçebilirsin.

            Args:
                hafta: Hangi hafta için plan kurulacak.
            """
            toolset.calls.append(f"plan_hazirla(hafta={hafta})")
            with toolset.session_factory() as db:
                week_start = (
                    this_week_start(timezone=toolset.settings.timezone)
                    if hafta == "bu_hafta"
                    else next_week_start(timezone=toolset.settings.timezone)
                )
                planner = MealPlannerService(db, toolset.settings)
                existing = planner.current_session(week_start)
                if existing and existing.state in (SessionState.APPROVED, SessionState.PUBLISHED):
                    return (
                        f"{week_start} haftası zaten onaylanmış/yayınlanmış. "
                        "Yeni plan kuramam; kullanıcıya bunu söyle."
                    )
                hard = PreferenceService(db).hard_rules()
                selector = CandidateSelector(db)
                scorer = CandidateScorer(db)
                last_seen = scorer.last_seen()
                rejected = FeedbackService(db).rejected_counts()
                dates = week_dates(week_start)
                base = toolset.settings.meal_slots[0] if toolset.settings.meal_slots else "dinner"
                rules = MealRules.from_db(db)
                suggested = Counter(course_role(slot) for slot in rules.settings_for_plan(toolset.settings).planning_slots)
                lines = [
                    f"Hafta: {week_start} - {week_end(week_start)}",
                    "Günler: " + ", ".join(f"{d.isoformat()} {TR_DAY_NAMES[d.weekday()]}" for d in dates),
                    "",
                    "Önerilen gün şekli (ZORUNLU DEĞİL, kullanıcı başka istiyorsa ona uy): "
                    + ", ".join(f"{count}x {role}" for role, count in suggested.items()),
                    f"Slot adlandırma: {base}_main, {base}_meze, {base}_salad, {base}_side, "
                    f"{base}_soup. Aynı rolden birden fazlaysa {base}_meze_1, {base}_meze_2.",
                    "",
                    "Aday havuzu (rol başına, puan sırasına göre):",
                ]
                meze_target = rules.weekly_meze_target(toolset.settings)
                if meze_target > 0:
                    lines.append(
                        f"MEZELER GÜNLERE BÖLÜNMEZ: haftada {meze_target} mezelik ayrı bir liste kur. "
                        f"plan_kaydet'te her biri 'HAFTA|{WEEKLY_BASE}_meze_1|Haydari' biçiminde "
                        f"({WEEKLY_BASE}_meze_1 ... {WEEKLY_BASE}_meze_{meze_target}). Günlük öğünlere meze koyma; "
                        "aşağıdaki meze havuzundan seç."
                    )
                lines.extend(["Kalıcı kurallar:", *rules.summary()])
                for base in toolset.settings.meal_slots:
                    lines.append(f"\nÖğün: {base}")
                    for role in ("main", "meze", "salad", "side", "soup"):
                        candidates = selector.select(base, hard, week_start, course_role=role)
                        scored = scorer.score_with_values(candidates, dates[0], Counter())
                        lines.append(
                            f"\n{role} (uygun kategoriler: "
                            f"{', '.join(allowed_categories_for_role(role))}) - {len(scored)} aday:"
                        )
                        if not scored:
                            lines.append("  (aday yok)")
                            continue
                        for score, recipe in scored[:10]:
                            seen = last_seen.get(recipe.id)
                            seen_text = f"son {seen.isoformat()}" if seen else "yeni"
                            red = rejected.get(recipe.id, 0)
                            red_text = f", {red}x çıkarıldı" if red else ""
                            effort = (recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)
                            effort_text = f", {effort} dk" if effort else ""
                            lines.append(
                                f"  {recipe.name} | {score:.0f}p | {seen_text}{red_text}"
                                f"{', ' + recipe.protein_type if recipe.protein_type else ''}{effort_text} | {nutrition_text(recipe)}"
                            )
                target = rules.new_dish_target(toolset.settings)
                if target > 0:
                    from app.planner.novelty import untried_candidates

                    lines.append(
                        f"\nYENİ YEMEKLER: Bu hafta menüye en az {target} yeni yemek koy (kütüphanede "
                        "olmayan, ailenin daha önce yemediği, biraz sıradışı: başka bir mutfaktan, "
                        "mevsimlik ya da klasik bir yemeğin farklı yorumu; ev kurallarına uygun). "
                        "Aşağıdaki denenmemiş adaylardan seçebilir ya da yenisini kendin bulabilirsin: "
                        "önce tarif_ekle ile kaydet, sonra plan_kaydet'e koy. Yeni yemekleri farklı "
                        "günlere yay; menüde 'yeni' diye işaretlenirler."
                    )
                    untried = untried_candidates(db, rules)
                    if untried:
                        lines.append("Denenmemiş aday tarifler:")
                        lines += [f"  {_describe(recipe)}" for recipe in untried[:8]]
                lines.append(
                    "\n'kalori/protein bilgisi yok' olan tarifleri, ev kurallarında kalori "
                    "ya da protein şartı varsa, kullanmadan önce besin_degeri_kaydet ile "
                    "tahmin edip kaydet; yoksa plan_kaydet kalori sınırını denetleyemez."
                )
                return "\n".join(lines)

        @beta_async_tool
        async def plan_kaydet(
            ogunler: list[str],
            hafta: Literal["gelecek_hafta", "bu_hafta"] = "gelecek_hafta",
            notlar: str = "",
        ) -> str:
            """Kurduğun haftalık planı kaydeder. Önce `plan_hazirla` çağır.

            Günün şeklini sen belirlersin; bir güne tek öğün de koyabilirsin,
            hiç koymayabilirsin de (o gün satır yazma).

            Args:
                ogunler: Her satır "TARİH|SLOT|TARİF ADI". Örn:
                    "2026-10-20|dinner_main|Fırında Tavuk". Slot: dinner_main,
                    dinner_meze, dinner_salad, dinner_side, dinner_soup; aynı
                    rolden iki tane varsa dinner_side_1, dinner_side_2.
                    Haftalık meze listesi: "HAFTA|hafta_meze_1|Haydari".
                hafta: Hangi hafta.
                notlar: İzlediğin mantık, bir iki cümle.
            """
            toolset.calls.append(f"plan_kaydet({len(ogunler)} öğün, hafta={hafta})")
            with toolset.session_factory() as db:
                week_start = (
                    this_week_start(timezone=toolset.settings.timezone)
                    if hafta == "bu_hafta"
                    else next_week_start(timezone=toolset.settings.timezone)
                )
                planner = MealPlannerService(db, toolset.settings)
                session = planner.current_session(week_start)
                if session and session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
                    return f"{week_start} haftası onaylanmış/yayınlanmış, üzerine yazamam."

                valid_dates = {d.isoformat() for d in week_dates(week_start)}
                valid_bases = set(toolset.settings.meal_slots)
                rules = MealRules.from_db(db)
                meze_target = rules.weekly_meze_target(toolset.settings)
                service = RecipeService(db)
                parsed: dict[tuple[str, str], Recipe] = {}
                problems: list[str] = []
                for raw in ogunler:
                    parts = [part.strip() for part in raw.split("|")]
                    if len(parts) != 3:
                        problems.append(f"'{raw}' üç alan değil (TARİH|SLOT|TARİF)")
                        continue
                    iso, slot, recipe_name = parts
                    if iso.upper() == "HAFTA" or is_weekly_slot(slot):
                        if not is_weekly_slot(slot):
                            slot = f"{WEEKLY_BASE}_meze_{sum(1 for _, sl in parsed if is_weekly_slot(sl)) + 1}"
                        iso = week_start.isoformat()
                    elif meze_target > 0 and course_role(slot) == "meze":
                        problems.append(
                            f"'{raw}': mezeler bu evde günlere bölünmüyor; 'HAFTA|{WEEKLY_BASE}_meze_N|{recipe_name}' "
                            "biçiminde haftalık listeye yaz"
                        )
                        continue
                    if iso not in valid_dates:
                        problems.append(
                            f"'{iso}' bu haftanın dışında ({week_start} - {week_end(week_start)})"
                        )
                        continue
                    if base_meal_slot(slot) not in valid_bases | {WEEKLY_BASE}:
                        problems.append(
                            f"'{slot}' tanınmıyor; slot adı "
                            f"{'/'.join(sorted(valid_bases))} ile başlamalı (örn. dinner_main)"
                        )
                        continue
                    if course_role(slot) not in KNOWN_ROLES:
                        problems.append(
                            f"'{slot}' rolü tanınmıyor; bilinen roller: {', '.join(sorted(KNOWN_ROLES))}"
                        )
                        continue
                    if (iso, slot) in parsed:
                        problems.append(f"'{iso}|{slot}' iki kez verilmiş")
                        continue
                    recipe = service.find_recipe(recipe_name)
                    if not recipe:
                        problems.append(
                            f"'{recipe_name}' kütüphanede yok; yeni bir yemekse önce tarif_ekle ile kaydet"
                        )
                        continue
                    role = course_role(slot)
                    if not is_weekly_slot(slot) and not selector_matches_role(db, recipe, role):
                        problems.append(
                            f"'{recipe.name}' ({recipe.category}) {slot} rolüne uymuyor; "
                            f"uygun kategoriler: {', '.join(allowed_categories_for_role(role))}"
                        )
                        continue
                    parsed[(iso, slot)] = recipe

                daily = {
                    key: r for key, r in parsed.items()
                    if not is_weekly_slot(key[1]) and toolset.settings.no_repeat_meals
                }
                mains = Counter(r.id for (iso, sl), r in daily.items() if course_role(sl) == "main")
                for recipe_id, count in mains.items():
                    if count > 1:
                        name = next(r.name for r in daily.values() if r.id == recipe_id)
                        problems.append(f"'{name}' ana yemek olarak {count} kez var; aynı ana yemek haftada bir kez olur")
                by_day: dict[str, set[str]] = {}
                for (iso, sl), r in daily.items():
                    by_day.setdefault(iso, set()).add(r.id)
                for iso, ids in by_day.items():
                    nxt = (date.fromisoformat(iso) + timedelta(days=1)).isoformat()
                    for recipe_id in ids & by_day.get(nxt, set()):
                        name = next(r.name for r in daily.values() if r.id == recipe_id)
                        problems.append(f"'{name}' {iso} ve {nxt} günlerinde arka arkaya; aynı yemek iki gün üst üste olmaz")
                # Hafta geçişi: önceki haftanın pazarı / sonraki haftanın pazartesisi.
                for edge, outside in ((week_start, week_start - timedelta(days=1)), (week_end(week_start), week_end(week_start) + timedelta(days=1))):
                    ids = by_day.get(edge.isoformat(), set())
                    if not ids:
                        continue
                    for item in db.scalars(select(MealPlanItem).where(MealPlanItem.date == outside, MealPlanItem.recipe_id.in_(ids))):
                        if not is_weekly_slot(item.meal_slot):
                            problems.append(
                                f"'{item.recipe.name}' {outside.isoformat()} günü de var (komşu hafta); arka arkaya iki gün olmaz"
                            )

                if problems:
                    report = ["Plan kaydedilmedi.", "Sorunlar:"]
                    report += [f"  - {p}" for p in problems[:15]]
                    report.append("Düzeltip tekrar çağır.")
                    return "\n".join(report)
                if not parsed:
                    return "Hiç geçerli öğün verilmedi, plan kaydedilmedi."

                await toolset._ensure_nutrition(db, list(parsed.values()))
                try:
                    # Yalnizca yazilan ogunler denetlenir: "pazar disaridayiz" gibi
                    # bos birakilan bir gun, yemek sayisi kuralini ihlal etmez.
                    rules.validate(
                        [(date.fromisoformat(iso), slot, recipe) for (iso, slot), recipe in parsed.items()]
                    )
                except RuleViolation as error:
                    return f"Plan kaydedilmedi: {error}"

                if session is None:
                    session = WeeklyPlanningSession(
                        week_start=week_start,
                        week_end=week_end(week_start),
                        state=SessionState.DRAFT_GENERATED,
                        admin_chat_id=toolset.settings.admin_telegram_user_id,
                    )
                    db.add(session)
                    db.flush()
                if session.meal_plan is None:
                    plan = MealPlan(session=session, status="draft")
                    db.add(plan)
                    db.flush()
                else:
                    plan = session.meal_plan
                    plan.status = "draft"
                    plan.items.clear()
                    db.flush()
                for (iso, slot), recipe in sorted(parsed.items()):
                    plan.items.append(
                        MealPlanItem(date=date.fromisoformat(iso), meal_slot=slot, recipe_id=recipe.id)
                    )
                session.state = SessionState.AWAITING_APPROVAL
                session.draft_version += 1
                if notlar.strip():
                    session.context = {**(session.context or {}), "agent_notes": notlar.strip()}
                db.commit()
                toolset.touched_session_id = session.id
                logger.info(
                    "agent_plan_saved session_id=%s week_start=%s items=%s",
                    session.id, week_start, len(parsed),
                )
                per_day = Counter(iso for iso, slot in parsed if not is_weekly_slot(slot))
                weekly_count = sum(1 for _, slot in parsed if is_weekly_slot(slot))
                new_names = [r.name for r in parsed.values() if r.status == RecipeStatus.CANDIDATE]
                target = MealRules.from_db(db).new_dish_target(toolset.settings)
                empty = sorted(valid_dates - set(per_day))
                summary = [
                    f"{week_start} - {week_end(week_start)} haftası kaydedildi ({len(parsed)} öğün).",
                    "Gün başına: " + ", ".join(f"{iso}={per_day[iso]}" for iso in sorted(per_day)),
                ]
                if empty:
                    summary.append("Öğün yazılmayan günler: " + ", ".join(empty))
                if weekly_count or meze_target:
                    summary.append(f"Haftanın mezeleri: {weekly_count} (hedef {meze_target}).")
                if new_names:
                    summary.append("Yeni yemekler (aday, menüde 'yeni' görünür): " + ", ".join(new_names))
                if len(new_names) < target:
                    summary.append(
                        f"UYARI: Bu hafta {target} yeni yemek hedefleniyor, planda {len(new_names)} var. "
                        "tarif_ekle ile yeni yemek kaydedip ogun_degistir ile ekle."
                    )
                summary.append(
                    "Kullanıcı onaylamak isterse /approve yazmalı; onaylanınca alıcılara "
                    "menü ve alışveriş listesi gider."
                )
                summary.append(render_plan(session))
                return "\n".join(summary)

        @beta_async_tool
        async def tarif_ekle(
            ad: str,
            kategori: Literal["main", "meze", "salad", "side", "soup"],
            malzemeler: list[str],
            hazirlanis: str = "",
            porsiyon: int = 4,
            hazirlik_dakika: int = 0,
            pisirme_dakika: int = 0,
            protein: str = "",
            vejetaryen: bool = False,
            kaynak: str = "",
        ) -> str:
            """Kütüphaneye yeni tarif ekler. ADAY kaydedilir: menüye
            konabilir ("yeni" diye görünür), ama kullanıcı `tarif_onayla`
            demeden kalıcı tarif listesine (otomatik seçim havuzuna) girmez.

            Args:
                ad: Tarifin adı.
                kategori: Yemeğin rolü.
                malzemeler: Her satır "miktar birim ad". Örn:
                    ["600 gr tavuk göğsü", "1 yemek kaşığı zeytinyağı", "tuz"].
                hazirlanis: Hazırlama adımları.
                porsiyon: Malzemeler kaç kişilik.
                hazirlik_dakika: Hazırlık süresi.
                pisirme_dakika: Pişirme süresi.
                protein: chicken, beef, fish, legumes, dairy, vegetable.
                vejetaryen: Et içermiyorsa true.
                kaynak: Kaynak URL veya site adı.
            """
            toolset.calls.append(f"tarif_ekle({ad!r}, kategori={kategori})")
            cleaned = ad.strip()
            if not cleaned:
                return "Tarif adı boş, kaydetmedim."
            if not malzemeler:
                return "Malzeme listesi boş. En az bir malzeme olmadan tarif kaydetmem."
            with toolset.session_factory() as db:
                service = RecipeService(db)
                existing = service.find_recipe(cleaned, include_inactive=True)
                if existing and existing.status == RecipeStatus.APPROVED:
                    return f"'{existing.name}' zaten onaylı tariflerde var, tekrar eklemedim."
                recipe = service.upsert_recipe(
                    RecipeInput(
                        name=cleaned,
                        category=kategori,
                        meal_type="dinner",
                        ingredients=[parse_ingredient(line) for line in malzemeler],
                        instructions=hazirlanis.strip() or None,
                        servings=max(1, porsiyon),
                        prep_minutes=hazirlik_dakika or None,
                        cook_minutes=pisirme_dakika or None,
                        protein_type=protein.strip().casefold() or None,
                        vegetarian=vejetaryen,
                        source=kaynak.strip() or "agent",
                        tags=["agent-eklendi"],
                        status="candidate",
                    )
                )
                logger.info("agent_recipe_added recipe_id=%s", recipe.id)
                return (
                    f"'{recipe.name}' aday tariflere eklendi ({len(recipe.ingredients)} malzeme). "
                    "plan_kaydet ya da ogun_degistir ile menüye koyabilirsin; menüde 'yeni' diye "
                    "görünür. Kalıcı listeye girmesi için kullanıcının beğenip onaylaması gerekir."
                )

        @beta_async_tool
        async def aday_tarifler() -> str:
            """Onay bekleyen aday (yeni) tarifleri listeler. Menüye konabilirler,
            ama otomatik seçim havuzunda değiller."""
            toolset.calls.append("aday_tarifler()")
            with toolset.session_factory() as db:
                candidates = RecipeService(db).list_candidates()
                if not candidates:
                    return "Onay bekleyen aday tarif yok."
                lines = [f"{len(candidates)} aday tarif (menüye 'yeni' olarak konabilir):"]
                for recipe in candidates:
                    source = f" · kaynak: {recipe.source}" if recipe.source else ""
                    lines.append(f"  - {_describe(recipe)}{source}")
                return "\n".join(lines)

        @beta_async_tool
        async def tarif_onayla(tarif_adi: str) -> str:
            """Aday tarifi onaylar; kalıcı tarif listesine girer ve sonraki
            haftalarda otomatik de seçilebilir. Kullanıcı beğendiğini ya da
            eklemek istediğini belli ettiğinde çağır.

            Args:
                tarif_adi: Onaylanacak aday tarifin tam adı.
            """
            toolset.calls.append(f"tarif_onayla({tarif_adi!r})")
            with toolset.session_factory() as db:
                if RecipeService(db).approve_candidate(tarif_adi.strip()):
                    logger.info("agent_candidate_approved")
                    return f"'{tarif_adi.strip()}' onaylandı, artık kalıcı tarif listesinde."
                return (
                    f"'{tarif_adi}' adında aday tarif bulamadım. "
                    "aday_tarifler ile listeyi görüp adı doğrulayabilirsin."
                )

        @beta_async_tool
        async def tarif_cikar(tarif_adi: str) -> str:
            """Bir tarifi pasifleştirir: artık menülere girmez ve aday
            listesinde görünmez. Sadece kullanıcı istediğinde çağır.

            Args:
                tarif_adi: Çıkarılacak tarifin tam adı.
            """
            toolset.calls.append(f"tarif_cikar({tarif_adi!r})")
            with toolset.session_factory() as db:
                if RecipeService(db).disable_recipe(tarif_adi.strip()):
                    logger.info("agent_recipe_disabled")
                    return f"'{tarif_adi.strip()}' pasifleştirildi."
                return f"'{tarif_adi}' bulunamadı."

        @beta_async_tool
        async def menuyu_onayla() -> str:
            """Aktif taslak menüyü onaylar; alıcılar tanımlıysa menü ve alışveriş
            listesi onlara Telegram'dan gönderilir. Onaylanan menü artık
            değiştirilemez. YALNIZCA kullanıcı bu mesajda açıkça onaylamak
            istediğini söylediyse çağır ("onayla", "tamam bu olsun, gönder");
            kendi başına asla çağırma.
            """
            toolset.calls.append("menuyu_onayla()")
            from app.workflow import WeeklyWorkflowService

            with toolset.session_factory() as db:
                session = toolset._resolve_session(db, "aktif")
                if session is None or not session.meal_plan or not session.meal_plan.items:
                    return "Onaylanacak bir menü yok."
                if session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
                    return f"{session.week_start} haftasının menüsü zaten onaylı."
                try:
                    MealPlannerService(db, toolset.settings).approve(session)
                except RuleViolation as error:
                    return f"Onaylanamadı, kurallara uymayan bir şey var: {error}"
                toolset.touched_session_id = session.id
                logger.info("agent_menu_approved session_id=%s", session.id)
                if (
                    not toolset.settings.telegram_menu_messages
                    or toolset.notifier is None
                    or not toolset.settings.all_recipient_ids
                ):
                    return (
                        f"{session.week_start} haftasının menüsü onaylandı. Uygulamada Onaylı menü'de; "
                        "tarifleri ve alışveriş listesi hazır, PDF olarak paylaşılabilir."
                    )
                try:
                    await WeeklyWorkflowService(db, toolset.settings, toolset.notifier).publish_final(session)
                except Exception:
                    logger.exception("agent_publish_failed session_id=%s", session.id)
                    return "Menü onaylandı ama alıcılara gönderilemedi; kullanıcıya söyle."
                return f"{session.week_start} haftasının menüsü onaylandı ve alıcılara Telegram'dan gönderildi."

        @beta_async_tool
        async def kiler(islem: Literal["goster", "ekle", "cikar"] = "goster", malzemeler: list[str] = []) -> str:
            """Evde hep bulunan malzemeler (kiler): alışveriş listesine girmezler.

            Args:
                islem: "goster" listeler, "ekle" ekler, "cikar" çıkarır.
                malzemeler: Eklenecek ya da çıkarılacak malzeme adları, örn.
                    ["tuz", "zeytinyağı"].
            """
            toolset.calls.append(f"kiler({islem}, {len(malzemeler)})")
            with toolset.session_factory() as db:
                names = [n for n in (normalize_name(m) for m in malzemeler) if n]
                if islem == "ekle":
                    for name in names:
                        if db.scalar(select(PantryItem).where(PantryItem.ingredient_name == name)) is None:
                            db.add(PantryItem(ingredient_name=name))
                    db.commit()
                elif islem == "cikar":
                    for name in names:
                        item = db.scalar(select(PantryItem).where(PantryItem.ingredient_name == name))
                        if item is not None:
                            db.delete(item)
                    db.commit()
                current = [p.ingredient_name for p in db.scalars(select(PantryItem).order_by(PantryItem.ingredient_name))]
                return ("Kilerde: " + ", ".join(current)) if current else "Kiler boş."

        return [
            plan_hazirla,
            plan_kaydet,
            plani_getir,
            tarif_ara,
            tarif_detay,
            ogun_degistir,
            ogun_ekle,
            ogun_cikar,
            yenisiyle_degistir,
            alisveris_listesi,
            gecmis_getir,
            kurallari_goster,
            kural_ekle,
            kural_sil,
            besin_degeri_kaydet,
            tarif_ekle,
            aday_tarifler,
            tarif_onayla,
            tarif_cikar,
            menuyu_onayla,
            kiler,
        ]
