from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from datetime import date, timedelta
from typing import Literal

from anthropic import beta_async_tool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, base_meal_slot, course_role
from app.db.models import (
    MealPlanItem,
    PantryItem,
    PreferenceType,
    Recipe,
    RecipeStatus,
    SessionState,
    WeeklyPlanningSession,
)
from app.formatting import course_label
from app.memory.feedback import FeedbackService
from app.memory.preferences import PreferenceService
from app.memory.rules import MealRules, RuleViolation
from app.recipes.nutrition import nutrition_text
from app.db.models import MealPlan
from app.planner.candidate_selector import CandidateSelector
from app.planner.dates import TR_DAY_NAMES, next_week_start, this_week_start, week_dates, week_end
from app.planner.scorer import CandidateScorer
from app.planner.service import MealPlannerService, allowed_categories_for_role
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService
from app.shopping.service import ShoppingListService

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
    current_day: date | None = None
    for item in sorted(session.meal_plan.items, key=lambda i: (i.date, i.meal_slot)):
        if item.date != current_day:
            current_day = item.date
            lines.append(f"\n{item.date.isoformat()} {TR_DAY_NAMES[item.date.weekday()]}:")
        servings = f", {item.servings} kişi" if item.servings else ""
        changed = " [admin değiştirdi]" if item.admin_changed else ""
        lines.append(
            f"  slot={item.meal_slot} ({course_label(item.meal_slot)}): "
            f"{item.recipe.name} [kategori={item.recipe.category}{servings}]{changed}"
        )
    from app.formatting import nutrition_plan_lines
    lines.extend(nutrition_plan_lines(session))
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

    def __init__(self, settings: Settings, session_factory: SessionFactory):
        self.settings = settings
        self.session_factory = session_factory
        self.calls: list[str] = []

    # --- yardimcilar -----------------------------------------------------

    def _resolve_session(self, db: Session, hafta: str) -> WeeklyPlanningSession | None:
        planner = MealPlannerService(db, self.settings)
        if hafta == "bu_hafta":
            return planner.this_week_session()
        if hafta == "gelecek_hafta":
            return planner.current_session()
        return planner.active_session()

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
                return render_plan(toolset._resolve_session(db, hafta))

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
        async def tarif_detay(tarif_adi: str) -> str:
            """Bir tarifin malzemelerini ve hazırlanışını döndürür.

            Args:
                tarif_adi: Tarifin tam adı.
            """
            toolset.calls.append(f"tarif_detay({tarif_adi!r})")
            with toolset.session_factory() as db:
                recipe = RecipeService(db).find_recipe(tarif_adi)
                if not recipe:
                    return f"'{tarif_adi}' adlı tarif bulunamadı. tarif_ara ile doğru adı arayabilirsin."
                lines = [_describe(recipe), f"{recipe.servings} porsiyon için malzemeler:"]
                for ing in recipe.ingredients:
                    qty = f"{ing.quantity:g} {ing.unit or ''}".strip() if ing.quantity is not None else "miktar yok"
                    lines.append(f"  - {qty} {ing.ingredient.name}")
                lines.append(f"Hazırlanış: {recipe.instructions or 'kayıtlı değil'}")
                return "\n".join(lines)

        @beta_async_tool
        async def ogun_degistir(tarih: str, yeni_tarif: str, gerekce: str, ogun_slotu: str = "") -> str:
            """Plandaki bir öğünü başka bir tarifle değiştirir. Onaylanmış veya
            yayınlanmış planlar değiştirilemez.

            Args:
                tarih: Değişecek günün ISO tarihi, örn. 2026-10-20.
                yeni_tarif: Yerine konacak tarifin adı. Kütüphanede bulunmalı.
                gerekce: Bu değişikliği neden yaptığın. Kaydedilir ve ileride
                    menü önerilirken hatırlanır.
                ogun_slotu: Günde birden fazla öğün varsa hangisi, örn.
                    dinner_main. Boş bırakılırsa yeni tarifin kategorisine uyan
                    öğün seçilir.
            """
            toolset.calls.append(f"ogun_degistir(tarih={tarih}, yeni_tarif={yeni_tarif!r}, slot={ogun_slotu!r})")
            try:
                target = date.fromisoformat(tarih.strip())
            except ValueError:
                return f"'{tarih}' geçerli bir ISO tarih değil. 2026-10-20 biçiminde ver."
            with toolset.session_factory() as db:
                session = toolset._resolve_session(db, "aktif")
                if not session or not session.meal_plan:
                    return "Değiştirilecek aktif bir plan yok."
                if session.state in (SessionState.APPROVED, SessionState.PUBLISHED):
                    return (
                        "Bu plan onaylanmış/yayınlanmış durumda, değiştirilemez. "
                        "Kullanıcıya /regenerate ile yeni taslak oluşturabileceğini söyle."
                    )
                replacement = RecipeService(db).find_recipe(yeni_tarif)
                if not replacement:
                    return f"'{yeni_tarif}' kütüphanede yok. tarif_ara ile doğru adı bul veya kullanıcıya eklemeyi teklif et."
                day_items = [i for i in session.meal_plan.items if i.date == target]
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
                if replacement.status != RecipeStatus.APPROVED:
                    return "Aday veya pasif tarif menüye konamaz."
                proposed = [(i.date, i.meal_slot, replacement if i is chosen else i.recipe) for i in session.meal_plan.items]
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
                logger.info(
                    "agent_meal_swapped session_id=%s date=%s slot=%s", session.id, target, chosen.meal_slot
                )
                return (
                    f"Değiştirildi: {tarih} {chosen.meal_slot} "
                    f"{original_name} -> {replacement.name}. Gerekçe kaydedildi."
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
        async def tercih_kaydet(kural: str, tip: Literal["hard", "soft"] = "hard") -> str:
            """Kalıcı bir tercihi hafızaya yazar. Yazmadan ÖNCE kullanıcıya
            kuralı nasıl anladığını söyle ve onayını al.

            Args:
                kural: Kuralın tek cümlelik, net hali. Örn: "Kırmızı et haftada
                    en fazla bir kez".
                tip: "hard" asla ihlal edilmemeli, "soft" mümkünse uyulsun.
            """
            toolset.calls.append(f"tercih_kaydet(kural={kural!r}, tip={tip})")
            cleaned = kural.strip()
            if not cleaned:
                return "Kural metni boş, kaydetmedim."
            with toolset.session_factory() as db:
                try:
                    PreferenceService(db).add(cleaned, PreferenceType(tip), source="agent")
                except ValueError as error:
                    return f"Kural kaydedilmedi: {error}"
                status = MealRules.from_db(db).summary()
                logger.info("agent_preference_saved tip=%s", tip)
                return f"Kaydedildi ({tip}): {cleaned}\n" + "\n".join(status)

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
                    rolden iki tane varsa dinner_meze_1, dinner_meze_2.
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
                service = RecipeService(db)
                parsed: dict[tuple[str, str], Recipe] = {}
                problems: list[str] = []
                for raw in ogunler:
                    parts = [part.strip() for part in raw.split("|")]
                    if len(parts) != 3:
                        problems.append(f"'{raw}' üç alan değil (TARİH|SLOT|TARİF)")
                        continue
                    iso, slot, recipe_name = parts
                    if iso not in valid_dates:
                        problems.append(
                            f"'{iso}' bu haftanın dışında ({week_start} - {week_end(week_start)})"
                        )
                        continue
                    if base_meal_slot(slot) not in valid_bases:
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
                        problems.append(f"'{recipe_name}' kütüphanede yok veya onaylı değil")
                        continue
                    if recipe.status != RecipeStatus.APPROVED:
                        problems.append(f"'{recipe.name}' aday durumda, menüye konamaz")
                        continue
                    role = course_role(slot)
                    if not selector_matches_role(db, recipe, role):
                        problems.append(
                            f"'{recipe.name}' ({recipe.category}) {slot} rolüne uymuyor; "
                            f"uygun kategoriler: {', '.join(allowed_categories_for_role(role))}"
                        )
                        continue
                    parsed[(iso, slot)] = recipe

                if problems:
                    report = ["Plan kaydedilmedi.", "Sorunlar:"]
                    report += [f"  - {p}" for p in problems[:15]]
                    report.append("Düzeltip tekrar çağır.")
                    return "\n".join(report)
                if not parsed:
                    return "Hiç geçerli öğün verilmedi, plan kaydedilmedi."

                try:
                    MealRules.from_db(db).validate(
                        [(date.fromisoformat(iso), slot, recipe) for (iso, slot), recipe in parsed.items()],
                        [(d, base) for d in week_dates(week_start) for base in toolset.settings.meal_slots],
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
                logger.info(
                    "agent_plan_saved session_id=%s week_start=%s items=%s",
                    session.id, week_start, len(parsed),
                )
                per_day = Counter(iso for iso, _ in parsed)
                empty = sorted(valid_dates - set(per_day))
                summary = [
                    f"{week_start} - {week_end(week_start)} haftası kaydedildi ({len(parsed)} öğün).",
                    "Gün başına: " + ", ".join(f"{iso}={per_day[iso]}" for iso in sorted(per_day)),
                ]
                if empty:
                    summary.append("Öğün yazılmayan günler: " + ", ".join(empty))
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
            """Kütüphaneye yeni tarif ekler. ADAY kaydedilir; kullanıcı
            `tarif_onayla` demeden menüye giremez.

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
                    "Menülerde kullanılabilmesi için kullanıcının onaylaması gerekiyor; "
                    "onaylamak isteyip istemediğini sor."
                )

        @beta_async_tool
        async def aday_tarifler() -> str:
            """Onay bekleyen aday tarifleri listeler. Bunlar menülere girmez."""
            toolset.calls.append("aday_tarifler()")
            with toolset.session_factory() as db:
                candidates = RecipeService(db).list_candidates()
                if not candidates:
                    return "Onay bekleyen aday tarif yok."
                lines = [f"{len(candidates)} aday tarif (menülere girmezler):"]
                for recipe in candidates:
                    source = f" · kaynak: {recipe.source}" if recipe.source else ""
                    lines.append(f"  - {_describe(recipe)}{source}")
                return "\n".join(lines)

        @beta_async_tool
        async def tarif_onayla(tarif_adi: str) -> str:
            """Aday tarifi onaylar; bundan sonra menülerde kullanılabilir.
            Sadece kullanıcı açıkça istediğinde çağır.

            Args:
                tarif_adi: Onaylanacak aday tarifin tam adı.
            """
            toolset.calls.append(f"tarif_onayla({tarif_adi!r})")
            with toolset.session_factory() as db:
                if RecipeService(db).approve_candidate(tarif_adi.strip()):
                    logger.info("agent_candidate_approved")
                    return f"'{tarif_adi.strip()}' onaylandı, artık menülerde kullanabilirim."
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

        return [
            plan_hazirla,
            plan_kaydet,
            plani_getir,
            tarif_ara,
            tarif_detay,
            ogun_degistir,
            alisveris_listesi,
            gecmis_getir,
            tercih_kaydet,
            tarif_ekle,
            aday_tarifler,
            tarif_onayla,
            tarif_cikar,
        ]
