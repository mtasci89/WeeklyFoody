"""Her gün internetten yeni tarifler (kullanıcı isteği: "Asistan her gün internette
gezinip, Instagram vs. yerlerden yeni tarifler eklesin, her gün 10 tane").

İki adım:
1. Google aramalı tek istek: yemek blogları, tarif siteleri ve sosyal medyada
   (Instagram, TikTok, YouTube) popüler olan, ev yemeğine uygun, biraz sıradışı
   tarifler kaynağıyla bulunur. Instagram'ın kendisi giriş istediği için doğrudan
   okunamaz; oradaki popüler tarifler arama sonucuna düşen sayfalarından gelir.
2. Bulunan metin yapılandırılmış tariflere çevrilir (miktarlı malzemeler, adımlar).

Kütüphanede/adaylarda olanlar, birbirinin benzeri olanlar ve ev kurallarına aykırı
olanlar elenir; kalanlar ADAY tarif olarak kaydedilir (Tarifler > Adaylar). Haftalık
menünün "yeni" yemekleri bu adaylardan seçilir. Hiçbir menüye girmemiş eski günlük
adaylar 30 gün sonra pasife alınır ki aday listesi şişmesin (silinmez).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

TAG = "gunluk-kesif"
EXPIRE_DAYS = 30
CATEGORIES = ("main", "side", "soup", "salad", "meze")

SCHEMA = {
    "type": "object",
    "properties": {
        "tarifler": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ad": {"type": "string"},
                    "kategori": {"type": "string", "enum": list(CATEGORIES)},
                    "mutfak": {"type": "string"},
                    "kaynak": {"type": "string"},
                    "neden": {"type": "string"},
                    "malzemeler": {"type": "array", "items": {"type": "string"}},
                    "hazirlanis": {"type": "string"},
                    "porsiyon": {"type": "integer"},
                    "hazirlik_dakika": {"type": "integer"},
                    "pisirme_dakika": {"type": "integer"},
                    "protein": {"type": "string"},
                    "vejetaryen": {"type": "boolean"},
                },
                "required": ["ad", "kategori", "malzemeler", "hazirlanis"],
            },
        }
    },
    "required": ["tarifler"],
}

MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")


def search_prompt(count: int, today: date, rules: list[str], avoid: list[str]) -> str:
    mains = max(1, round(count * 0.5))
    sides = max(1, round(count * 0.3))
    mezes = max(0, count - mains - sides)
    lines = [
        f"İnternette ara: bugün ({today.isoformat()}, {MONTHS[today.month - 1]}) yemek bloglarında, tarif "
        "sitelerinde (Nefis Yemek Tarifleri, Yemek.com, Refika'nın Mutfağı, BBC Good Food, NYT Cooking, Bon "
        "Appétit, Ottolenghi vb.) ve sosyal medyada (Instagram, TikTok, YouTube) popüler ya da yeni paylaşılmış, "
        f"evde yapılabilecek, biraz sıradışı {count + 4} tarif bul.",
        f"Yaklaşık {mains} akşam ana yemeği, {sides} yan yemek/çorba, {mezes} meze/salata olsun.",
        "Farklı mutfaklardan olsun (Türk, Akdeniz, Orta Doğu, Asya, Latin...), mevsimine uygun olsun, "
        "birbirine benzemesin. Normal markette bulunan malzemelerle, 4 kişilik.",
        "Her tarif için: adı, kategorisi, mutfağı, kaynağı (site adı ve bağlantısı), bir cümleyle neden ilginç, "
        "miktarlarıyla malzemeleri ve kısa hazırlanışı. Okumadığın tarifi uydurma.",
    ]
    if rules:
        lines += ["", "Evin kuralları (MUTLAKA uy):", *[f"- {r}" for r in rules]]
    if avoid:
        lines += ["", "Bunlar zaten biliniyor, önerme:", ", ".join(avoid)]
    return "\n".join(lines)


def structure_prompt(found: str, sources: list[str]) -> str:
    return (
        "Aşağıdaki arama sonucundaki tarifleri yapılandır. Her tarif için adı Türkçe yaz (yabancı adın yanına kısa "
        "Türkçe karşılığı olabilir), kategoriyi main/side/soup/salad/meze olarak seç, malzemeleri ayrı satırlarda "
        "miktarıyla yaz ('600 gr tavuk but', '1 yemek kaşığı zeytinyağı'), hazırlanışı 3-7 kısa adımda yaz, "
        "'kaynak' alanına site adını ve varsa bağlantıyı yaz. Metinde olmayan tarif ekleme.\n\n"
        f"ARAMA SONUCU:\n{found}\n\n" + ("KAYNAKLAR:\n" + "\n".join(sources) if sources else "")
    )


def _ideas(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("daily_discovery_unparseable")
        return []
    rows = data.get("tarifler", []) if isinstance(data, dict) else []
    ideas = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("ad", "")).strip()
        lines = [str(x).strip() for x in row.get("malzemeler") or [] if str(x).strip()]
        if name and len(lines) >= 2 and str(row.get("hazirlanis") or "").strip():
            ideas.append({**row, "ad": name, "malzemeler": lines})
    return ideas


def _variant(a: set[str], b: set[str]) -> bool:
    """Aynı günün önerileri birbirinin çeşitlemesi mi ("Nohutlu Ispanaklı Tagine" /
    "Ispanaklı Nohut Yemeği" gibi). Yalnızca ortak bir malzeme (iki tavuk yemeği) sorun değil."""
    shared = a & b
    return bool(shared) and (len(shared) >= 2 or shared == a or shared == b)


def expire_old(db, today: date | None = None) -> int:
    """Hiçbir menüye girmemiş, 30 günden eski günlük keşif adaylarını pasife alır."""
    from sqlalchemy import select

    from app.db.models import MealPlanItem, Recipe, RecipeStatus

    cutoff = datetime.combine((today or date.today()) - timedelta(days=EXPIRE_DAYS), datetime.min.time())
    used = set(db.scalars(select(MealPlanItem.recipe_id)))
    old = db.scalars(
        select(Recipe).where(Recipe.status == RecipeStatus.CANDIDATE, Recipe.created_at < cutoff)
    ).all()
    expired = 0
    for recipe in old:
        if TAG in (recipe.tags or []) and recipe.id not in used:
            recipe.status = RecipeStatus.INACTIVE
            expired += 1
    if expired:
        db.commit()
    return expired


async def discover_daily(db, search, ask_json, count: int = 10, today: date | None = None) -> list[str]:
    """`search(prompt) -> (metin, kaynaklar)` Google aramalı istek; `ask_json(prompt, şema)`.
    Kaydedilen aday tariflerin adlarını döndürür."""
    from app.agent.fresh import as_probe, key_words
    from app.agent.tools import parse_ingredient
    from app.memory.preferences import PreferenceService
    from app.memory.rules import MealRules
    from app.recipes.importer import RecipeInput
    from app.recipes.service import RecipeService

    today = today or date.today()
    service = RecipeService(db)
    prefs = PreferenceService(db)
    house = [*prefs.hard_rules(), *prefs.soft_rules()]
    rules = MealRules.from_db(db)
    known = [r.name for r in service.list_recipes(include_candidates=True)]
    saved: list[str] = []
    seen_keys: list[set[str]] = []
    for attempt in range(2):  # süzgeçten az geçerse bir kez daha ara
        need = count - len(saved)
        if need <= 0:
            break
        avoid = list(dict.fromkeys([*saved, *known]))[:300]
        try:
            found, sources = await search(search_prompt(need, today, house, avoid))
            if not found.strip():
                logger.warning("daily_discovery_empty_search attempt=%s", attempt)
                continue
            ideas = _ideas(await ask_json(structure_prompt(found, sources), SCHEMA))
        except Exception:
            logger.exception("daily_discovery_failed attempt=%s", attempt)
            continue
        for idea in ideas:
            if len(saved) >= count:
                break
            if service.find_recipe(idea["ad"], include_inactive=True) is not None or rules.excludes(as_probe(idea)):
                continue
            words = key_words(idea["ad"])
            if any(_variant(words, other) for other in seen_keys):
                continue
            category = str(idea.get("kategori") or "main").casefold()
            if category not in CATEGORIES:
                category = "main"
            source = str(idea.get("kaynak") or "").strip()[:450] or "internet (günlük keşif)"
            why = str(idea.get("neden") or "").strip()
            service.upsert_recipe(
                RecipeInput(
                    name=idea["ad"], category=category, meal_type="dinner",
                    cuisine=str(idea.get("mutfak") or "").strip() or None,
                    ingredients=[parse_ingredient(line) for line in idea["malzemeler"]],
                    instructions=str(idea.get("hazirlanis") or "").strip() or None,
                    servings=max(1, int(idea.get("porsiyon") or 4)),
                    prep_minutes=int(idea.get("hazirlik_dakika") or 0) or None,
                    cook_minutes=int(idea.get("pisirme_dakika") or 0) or None,
                    protein_type=str(idea.get("protein") or "").strip().casefold() or None,
                    vegetarian=bool(idea.get("vejetaryen")),
                    source=source, notes=f"Günlük keşif {today.isoformat()}. {why}".strip(),
                    tags=[TAG, "yeni-oneri"], status="candidate",
                )
            )
            saved.append(idea["ad"])
            seen_keys.append(words)
    logger.info("daily_discovery_saved count=%s", len(saved))
    return saved
