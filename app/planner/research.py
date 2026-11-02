"""Fresh web research for a menu; the library supplies history, never a fallback.

Search and structure calls are separate. A structured recipe must cite a URL
returned by the grounded search and have its name in the searched text. Nothing
is saved until every requested slot has a usable recipe.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
import logging

from app.agent.fresh import MAIN_ROLE_RULE, as_probe, key_words, parse_ideas
from app.config import WEEKLY_BASE, course_role, is_weekly_slot
from app.db.models import MealPlanItem, Recipe
from app.llm.base import PlannedMeal, WeeklyPlanOutput
from app.memory.rules import MealRules
from app.planner.dates import week_dates
from app.planner.pairing import pairing_penalty, protein_group
from app.recipes.importer import RecipeInput
from app.recipes.roles import matches_course_role, recipe_category

logger = logging.getLogger(__name__)

TAG = "menu-arastirmasi"
# Google araması kotaya/erişime takılınca yemekler aramasız, modelin bilgisiyle önerilir.
OFFLINE_SOURCE = "Foody yapay zekâ önerisi (internet araması o an kullanılamadı)"
OFFLINE_NOTE = (
    "Not: Google araması şu an kotaya takıldığı için bu yemekleri yapay zekâ internete bakmadan, "
    "kendi bilgisiyle önerdi (kaynak bağlantısı yok). Kurallar, roller ve tekrar denetimleri aynen uygulandı."
)
SEARCH_BATCH_SIZE = 4
URL = re.compile(r"https://[^\s<>\"\[\]]+")


class MenuResearchError(ValueError):
    pass


def search_unavailable(error) -> bool:
    """Arama özelliği kota/erişim yüzünden kullanılamıyor mu (aramasız öneri yapılabilir)."""
    from app.agent.gemini_backend import GeminiCapabilityError
    if isinstance(error, GeminiCapabilityError):
        return True
    code = getattr(error, "code", None)
    message = str(getattr(error, "message", "") or "").casefold()
    return code in (429, 403) or any(word in message for word in ("billing", "paid tier", "payment"))


def research_failure(error, stage):
    """Actionable provider errors, without copying request URLs or credentials."""
    import httpx
    from app.agent.gemini_backend import GeminiCapabilityError
    code = getattr(error, "code", None)
    message = str(getattr(error, "message", "") or "").casefold()
    if isinstance(error, GeminiCapabilityError):
        reason = str(error) + "."
    elif code == 429:
        from app.agent.gemini_backend import quota_scope
        scope = quota_scope(error)
        model = getattr(error, "foody_model", "")
        where = f" (son denenen: {model})" if model else ""
        if scope == "günlük":
            reason = (f"Denenen tüm Gemini modellerinin günlük Google arama kotası doldu{where}. "
                      "Kota gece yenilenir; yarın tekrar dene.")
        elif scope == "dakikalık":
            reason = (f"Gemini'nin dakikalık sınırı doldu{where}; sunucu bekleyip yedek modelleri de denedi. "
                      "Bir iki dakika sonra tekrar dene.")
        else:
            reason = (f"Gemini/Google arama kotası aşıldı (429){where}; yedek modeller de denendi. "
                      "Birkaç dakika sonra tekrar dene; yine olursa günlük kota dolmuştur.")
    elif any(word in message for word in ("billing", "paid tier", "payment")):
        reason = f"Google araması bu API hesabında ücretlendirme/erişim gerektiriyor ({code})."
    elif code == 401 or "api key" in message or "api_key" in message:
        reason = "Gemini API anahtarı kabul edilmedi; sunucudaki anahtar kontrol edilmeli."
    elif code == 403:
        reason = "Google/Gemini bu API hesabının arama erişimini reddetti (403)."
    elif code == 404:
        reason = "Yapılandırılmış Gemini modelleri bulunamadı (404)."
    elif code == 400:
        reason = "Google/Gemini isteği reddetti (400); seçili modellerin arama veya yanıt biçimi desteği uygun değil."
    elif isinstance(error, (TimeoutError, httpx.TimeoutException)) or code == 504:
        reason = "Google/Gemini yanıtı zamanında gelmedi; daha az yemeği birlikte deneyebilirsin."
    elif isinstance(error, (OSError, httpx.NetworkError)):
        reason = "Sunucu Google/Gemini bağlantısını kuramadı; telefonun internet bağlantısıyla ilgili bir sonuç değil."
    elif code is not None and code >= 500:
        reason = f"Google/Gemini hizmeti geçici olarak kullanılamıyor ({code})."
    else:
        reason = f"Arama yanıtı işlenemedi ({type(error).__name__})."
    return f"{stage}: {reason} Menü değiştirilmedi."


def normalized(text: str) -> str:
    return " ".join(text.casefold().replace("i\u0307", "i").translate(str.maketrans("çğıöşü", "cgiosu")).split())


def source_url(text: str) -> str | None:
    for match in URL.finditer(text or ""):
        value = match.group().rstrip(".,;:)»}")
        parsed = urlsplit(value)
        if parsed.hostname and not parsed.username and not parsed.password:
            return value
    return None


def cooking_method(recipe) -> str:
    text = normalized(recipe.name + " " + (getattr(recipe, "instructions", None) or ""))
    for name, words in (("fırın", ("firin", "roast", "baked")), ("ızgara", ("izgara", "grill")),
                        ("sote", ("sote", "wok", "stir fry")), ("yahni", ("yahni", "guvec", "tagine", "tencere"))):
        if any(word in text for word in words):
            return name
    return ""


def similarity(recipe, previous) -> float:
    """Sauce/name changes alone are not a new dish; protein alone is not a ban."""
    a, b = key_words(recipe.name), key_words(previous.name)
    if normalized(recipe.name) == normalized(previous.name):
        return 1.0
    overlap = len(a & b) / max(1, len(a | b))
    method = cooking_method(recipe)
    same_method = method and method == cooking_method(previous)
    shared_core = bool(a & b) and (a <= b or b <= a or overlap >= 0.6)
    if same_method and shared_core and protein_group(recipe) and protein_group(recipe) == protein_group(previous):
        return max(overlap, 0.85)
    return overlap if len(a & b) >= 2 else 0.0


@dataclass(frozen=True)
class Target:
    day: date
    slot: str
    role: str
    plate: str = ""

    @property
    def key(self):
        return self.day, self.slot


def targets_for_week(settings, rules, week_start):
    effective = rules.settings_for_plan(settings)
    targets = [Target(day, slot, course_role(slot)) for day in week_dates(week_start) for slot in effective.planning_slots]
    targets += [Target(week_start, f"{WEEKLY_BASE}_meze_{i + 1}", "meze")
                for i in range(rules.weekly_meze_target(settings))]
    return targets


def history(db, week_start):
    from sqlalchemy.orm import selectinload
    from app.db.models import RecipeIngredient
    return list(db.scalars(select(Recipe).join(MealPlanItem).where(
        MealPlanItem.date >= week_start - timedelta(weeks=4), MealPlanItem.date <= week_start + timedelta(days=6),
    ).options(selectinload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient)).distinct()))


class WebMenuResearch:
    def __init__(self, settings, search=None, ask=None):
        self.settings, self.search, self.ask = settings, search, ask
        self.request = ""
        # True: Google araması kullanılamadı, öneriler aramasız (modelin bilgisiyle).
        self.offline = False
        self.offline_reason = ""

    def connect(self):
        if not self.settings.agent_web_search_enabled:
            raise MenuResearchError("Sunucuda web araması kapalı; menü değiştirilmedi.")
        if self.search is not None and self.ask is not None:
            return
        from app.agent.ai import ai_available, make_backend
        if not ai_available(self.settings) or not self.settings.agent_web_search_enabled:
            raise MenuResearchError("İnternetten menü araştırması kullanılamıyor. Yapay zekâ anahtarı (Groq) ve web araması gerekli; eski tariflerle menü doldurulmadı.")
        backend = make_backend(self.settings)
        self.search, self.ask = backend.search_text, backend.generate_json

    async def find(self, targets, known, recent, rules, request="") -> dict[tuple, dict]:
        # Bound response size and the number of sources needed in each request.
        # Keep main dishes before sides, including bulk replacements.
        result = {}
        groups = ([t for t in targets if t.role == "main"], [t for t in targets if t.role != "main"])
        for group in groups:
            for start in range(0, len(group), SEARCH_BATCH_SIZE):
                batch = []
                for target in group[start:start + SEARCH_BATCH_SIZE]:
                    main = ", ".join(row["ad"] for key, row in result.items()
                                     if key[0] == target.day and row.get("kategori") == "main")
                    plate = f"Yeni ana yemek: {main}. {target.plate}" if main and target.role != "main" and not is_weekly_slot(target.slot) else target.plate
                    batch.append(Target(target.day, target.slot, target.role, plate))
                found = await self._find_batch(batch, [*known, *[row["ad"] for row in result.values()]], recent, rules, request)
                result.update(found)
        return result

    async def _find_batch(self, targets, known, recent, rules, request="") -> dict[tuple, dict]:
        from app.agent.daily_discovery import SCHEMA as RECIPE_SCHEMA
        from copy import deepcopy
        self.connect()
        schema = deepcopy(RECIPE_SCHEMA)
        item = schema["properties"]["tarifler"]["items"]
        item["properties"].update({"icin": {"type": "integer"}, "kcal": {"type": "number"}, "protein_g": {"type": "number"}})
        item["required"] += ["icin", "neden"]
        offline_schema = deepcopy(schema)
        item["required"] += ["kaynak"]
        found = {}
        known_names = {normalized(name) for name in known}
        for attempt in range(2):
            pending = [target for target in targets if target.key not in found]
            if not pending:
                break
            listing = "\n".join(f"{i}) {t.day}: {t.slot}, rol={t.role}; tabak: {t.plate or 'ana yemekle uyumlu seç'}"
                                for i, t in enumerate(pending, 1))
            prompt = (
                "İnternette GERÇEK tarifleri araştır; eski kütüphaneden menü seçme. Aşağıdaki her hedef için "
                "iki farklı alternatif bul. Önceki yemeklerin yalnız sosunu/adını değiştirme. "
                "Normal market malzemeleri, mevsim, farklı mutfaklar ve pişirme yöntemleri düşün. "
                "Et/tavuk/balık/baklagil dengesi kur; aynı proteinin farklı yöntemlerle kullanılması yasak değil. "
                "Yemek siteleri ve erişilebilen Instagram/YouTube tariflerinden yararlan; erişemediğin sayfayı okumuş gibi yapma. "
                "Her hedef numarasını, tam Türkçe adı, kaynak URL, miktarlı malzemeler, porsiyon ve gerçek hazırlanış adımlarını yaz. "
                "Günün ana yemeği ve yan yemeği birbiriyle uyumlu olsun; ikisi birden nişastalı olmasın. "
                + MAIN_ROLE_RULE + "\nHEDEFLER:\n" + listing
                + "\nİSTEK:\n" + request[:3000]
                + "\nEV KURALLARI:\n" + "\n".join(rules.summary())
                + "\nSON DÖRT HAFTA (benzerlerini araştırma):\n" + ", ".join(r.name for r in recent)[:3000]
                + "\nKÜTÜPHANE (bunları yeniden seçme):\n" + ", ".join(known)[:4000]
                + "\nBU ARAŞTIRMADA SEÇİLENLER:\n" + ", ".join(row["ad"] for row in found.values())
            )
            stage = "Google araması"
            try:
                if not self.offline:
                    try:
                        text, sources = await self.search(prompt)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        if not search_unavailable(error):
                            raise
                        # Kota dolu diye kullanıcıyı eli boş bırakma: aramasız öner.
                        self.offline_reason = research_failure(error, "Google araması").removesuffix(" Menü değiştirilmedi.")
                        logger.warning("menu_research_offline reason=%s", self.offline_reason)
                        self.offline = True
                if self.offline:
                    stage = "Yapay zekâ önerisi"
                    text, sources, allowed = "", [], set()
                    raw = await self.ask(
                        "İnternet araması şu an kullanılamıyor. Aşağıdaki hedefler için internete bakmadan, "
                        "iyi bildiğin, gerçekten pişirilen ve evde yapılabilen tarifler öner; yemek uydurma. "
                        "'icin' hedef numarasıdır. Tam Türkçe ad, miktarlı malzemeler, porsiyon ve gerçek "
                        "hazırlanış adımları yaz. 'neden' yemeğin günün tabağına ve haftanın çeşitliliğine nasıl "
                        "uyduğunu anlatsın. 'kaynak' alanını boş bırak. 'kcal' ve 'protein_g' bir porsiyon için "
                        "tahmindir; bilinmiyorsa yazma.\n\n" + prompt.replace(
                            "İnternette GERÇEK tarifleri araştır; eski kütüphaneden menü seçme. ", ""
                        ).replace(
                            "Yemek siteleri ve erişilebilen Instagram/YouTube tariflerinden yararlan; erişemediğin sayfayı okumuş gibi yapma. ", ""
                        ).replace("kaynak URL, ", ""),
                        offline_schema,
                    )
                    ideas = parse_ideas(raw)
                else:
                    allowed = {url for s in sources for url in [source_url(s)] if url}
                    if not text.strip() or not allowed:
                        continue
                    stage = "Tarif yanıtını hazırlama"
                    raw = await self.ask(
                    "Yalnız aşağıdaki arama sonucundaki tarifleri yapılandır. 'icin' hedef numarasıdır. "
                    "Her hedef için en fazla 2 tarif yaz; hazırlanış en fazla 5 kısa adım olsun. "
                    "Adı arama metnindeki Türkçe adıyla birebir koru. 'kaynak' yalnız KAYNAKLAR listesindeki "
                    "ilgili tam HTTPS bağlantısı olsun. Okunmayan tarif/malzeme/adım uydurma. 'neden' bu "
                    "yemeğin günün tabağına ve haftanın çeşitliliğine nasıl uyduğunu anlatsın. Miktarları aynen koru. "
                    "'kcal' ve 'protein_g' bir porsiyon için tahmindir; bilinmiyorsa alanları yazma.\n"
                    + listing + "\nARAMA:\n" + text + "\nKAYNAKLAR:\n" + "\n".join(sources), schema,
                    )
                    ideas = parse_ideas(raw)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise MenuResearchError(research_failure(error, stage)) from error
            taken = {normalized(row["ad"]) for row in found.values()}
            for index, target in enumerate(pending, 1):
                choices = []
                for idea in ideas:
                    if idea.get("icin") != index:
                        continue
                    name = normalized(idea["ad"])
                    if self.offline:
                        url = OFFLINE_SOURCE
                        if name in known_names | taken:
                            continue
                    else:
                        url = source_url(str(idea.get("kaynak") or ""))
                        if url not in allowed or name not in normalized(text) or name in known_names | taken:
                            continue
                    probe = as_probe(idea)
                    probe.category = str(idea.get("kategori") or target.role)
                    probe.instructions = str(idea.get("hazirlanis") or "")
                    if not matches_course_role(probe, target.role) or rules.excludes(probe):
                        continue
                    if not probe.instructions.strip() or not str(idea.get("neden") or "").strip():
                        continue
                    from app.recipes.ingredient_lines import parse_ingredient
                    ingredients = [parse_ingredient(line) for line in idea["malzemeler"]]
                    if not any(i.quantity is not None and i.quantity > 0 for i in ingredients):
                        continue
                    closest = max((similarity(probe, old) for old in recent), default=0)
                    if closest >= 0.8:  # a different sauce is not a new recipe
                        continue
                    score = closest * 4
                    if target.role == "main":
                        chosen_mains = [as_probe(row) for row in found.values() if row.get("kategori") == "main"]
                        group = protein_group(probe)
                        score += sum(1 for old in chosen_mains if group and group == protein_group(old)) * 0.6
                        if chosen_mains and group and group == protein_group(chosen_mains[-1]):
                            score += 2
                    if target.role in {"side", "soup", "salad"} and target.plate:
                        score += pairing_penalty(target.plate, idea)
                    choices.append((score, idea, url, recipe_category(probe)))
                if choices:
                    _, chosen, url, category = min(choices, key=lambda row: row[0])
                    found[target.key] = {**chosen, "kaynak": url, "kategori": category}
                    taken.add(normalized(chosen["ad"]))
        missing = [f"{t.day} {t.slot}" for t in targets if t.key not in found]
        if missing and self.offline:
            raise MenuResearchError(self.offline_reason + " İnternete bakmadan önerilen yemekler de yetmedi: "
                                    + ", ".join(missing) + ". Menü değiştirilmedi.")
        if missing:
            raise MenuResearchError("Kaynağı ve tarifi doğrulanmış yeni yemek bulunamadı: " + ", ".join(missing)
                                    + ". Menü değiştirilmedi; araştırmayı yeniden deneyebilirsin.")
        return found

    async def prepare(self, db, week_start):
        from app.recipes.service import RecipeService
        from app.recipes.ingredient_lines import parse_ingredient
        rules = MealRules.from_db(db)
        if rules.new_dishes == 0:
            raise MenuResearchError("'Yeni yemek ekleme' kuralı internetten yeni menüyle çelişiyor. Önce bu kuralı düzenleyin veya açıkça kütüphaneden menü isteyin.")
        targets = targets_for_week(self.settings, rules, week_start)
        old = list(db.scalars(select(Recipe)))
        known = [name for r in old for name in [r.name, *(r.aliases or [])]]
        recent = history(db, week_start)
        async with asyncio.timeout(min(480, self.settings.agent_job_timeout_seconds)):
            mains = [t for t in targets if t.role == "main"]
            rows = await self.find(mains, known, recent, rules, self.request)
            others = []
            for t in targets:
                if t.role == "main":
                    continue
                plate = ", ".join(row["ad"] for key, row in rows.items() if key[0] == t.day and not is_weekly_slot(t.slot))
                others.append(Target(t.day, t.slot, t.role, plate))
            rows.update(await self.find(others, [*known, *[r["ad"] for r in rows.values()]], recent, rules, self.request))
        # All slots passed source/name/role/history checks before the first write.
        service = RecipeService(db)
        if any(service.find_recipe(row["ad"], include_inactive=True) for row in rows.values()):
            raise MenuResearchError("Araştırma sırasında aynı tarif başka bir işlemde kaydedildi; mevcut menü korundu. Yeniden araştırmayı deneyin.")
        result = []
        for target in targets:
            row = rows[target.key]
            values = dict(
                name=row["ad"], category=row["kategori"], meal_type=self.settings.meal_slots[0],
                ingredients=[parse_ingredient(line) for line in row["malzemeler"]],
                servings=max(1, int(row.get("porsiyon") or self.settings.default_servings)),
                instructions=row["hazirlanis"], cuisine=row.get("mutfak"), source=row["kaynak"],
                notes=str(row["neden"]).strip(), tags=[TAG, f"menu-hafta:{week_start.isoformat()}"],
                status="candidate", protein_type=row.get("protein"), vegetarian=bool(row.get("vejetaryen")),
            )
            if row.get("kcal") is not None or row.get("protein_g") is not None:
                values["nutrition"] = {"calories_kcal": row.get("kcal"), "protein_g": row.get("protein_g"),
                                       "source": "Foody: tarif malzemelerinden yapay zekâ tahmini", "estimated": True}
            recipe = service.upsert_recipe(RecipeInput(**values), commit=False)
            result.append((target, recipe))
        rules.validate([(t.day, t.slot, recipe) for t, recipe in result])
        output = WeeklyPlanOutput(meals=[PlannedMeal(date=t.day.isoformat(), meal_slot=t.slot, recipe_id=r.id)
                                        for t, r in result], notes="İnternetten yeni araştırma; ana yemekler önce, uyumlu yan yemekler sonra.")
        return output, result


def researcher_for(settings, estimator=None):
    return WebMenuResearch(settings, getattr(estimator, "search_text", None), getattr(estimator, "ask_json", None))
