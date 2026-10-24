"""Bir öğün için kütüphanede OLMAYAN yeni yemek önerisi üretmek.

Kullanıcı "dünyada başka yemek yok mu? yeni tarif diyorum hâlâ aynı şeyler" dedi:
ajan "yeni" isteğinde kütüphaneden seçmeye devam ediyordu. Bu modül modele tek bir
yapılandırılmış istekle, kaçınılacak yemekleri ve ev kurallarını vererek tarifiyle
birlikte birkaç yeni yemek ürettirir; uygun olan ilki menüye konur.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace

logger = logging.getLogger(__name__)

SOURCE = "yapay zekâ önerisi (Foody)"
ROLE_TEXT = {
    "main": "akşam yemeği ana yemeği",
    "meze": "meze",
    "salad": "salata",
    "side": "ana yemeğin yanına yan yemek (pilav, makarna, sebze, tahıl)",
    "soup": "çorba",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "tarifler": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ad": {"type": "string"},
                    "mutfak": {"type": "string"},
                    "neden": {"type": "string"},
                    "malzemeler": {"type": "array", "items": {"type": "string"}},
                    "hazirlanis": {"type": "string"},
                    "porsiyon": {"type": "integer"},
                    "hazirlik_dakika": {"type": "integer"},
                    "pisirme_dakika": {"type": "integer"},
                    "protein": {"type": "string"},
                    "vejetaryen": {"type": "boolean"},
                },
                "required": ["ad", "malzemeler", "hazirlanis"],
            },
        }
    },
    "required": ["tarifler"],
}


def build_prompt(role: str, replacing: str, request: str, avoid: list[str], rules: list[str], count: int) -> str:
    lines = [
        f"Bir ailenin haftalık menüsü için {count} YENİ {ROLE_TEXT.get(role, role)} önerisi üret.",
        f"Değiştirilen yemek: {replacing}." if replacing else "",
        f"Kullanıcının isteği: {request}" if request.strip() else "Kullanıcı yeni, biraz sıradışı bir şey istiyor.",
        "",
        "Kurallar:",
        "- Hepsi farklı mutfaklardan olsun (ör. Akdeniz, Asya, Latin, Orta Doğu, modern Türk) ve birbirine benzemesin.",
        "- Evde, normal bir markette bulunan malzemelerle yapılabilsin; 4 kişilik.",
        "- Aşağıdaki 'kaçınılacak yemekler'den hiçbiri, onların küçük varyasyonu ya da aynı ana malzeme + aynı pişirme "
        "olmasın (ör. fırında tavuğun başka bir soslusu yeni sayılmaz).",
        "- Malzemeleri ayrı satırlarda miktarıyla yaz: '600 gr tavuk but', '1 yemek kaşığı zeytinyağı'.",
        "- Hazırlanışı 3-6 kısa adımda yaz. 'neden' alanında bir cümleyle neden ilginç olduğunu söyle.",
        "- Yemek adlarını Türkçe yaz (yabancı adın yanına kısa Türkçe karşılığı olabilir).",
    ]
    if rules:
        lines += ["", "Evin kuralları (MUTLAKA uy):", *[f"- {r}" for r in rules]]
    if avoid:
        lines += ["", "Kaçınılacak yemekler (zaten biliniyor ya da yakında yenmiş):", ", ".join(avoid)]
    return "\n".join(line for line in lines if line is not None)


def parse_ideas(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        logger.warning("fresh_ideas_unparseable")
        return []
    rows = data.get("tarifler", []) if isinstance(data, dict) else []
    ideas = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("ad", "")).strip()
        ingredients = [str(x).strip() for x in row.get("malzemeler") or [] if str(x).strip()]
        if not name or len(ingredients) < 2:
            continue
        ideas.append({**row, "ad": name, "malzemeler": ingredients})
    return ideas


def as_probe(idea: dict):
    """MealRules.excludes ile denetlenebilsin diye kaydetmeden önceki taslak tarif."""
    return SimpleNamespace(
        name=idea["ad"],
        protein_type=str(idea.get("protein") or ""),
        aliases=[],
        tags=[],
        ingredients=[SimpleNamespace(ingredient=SimpleNamespace(name=line)) for line in idea["malzemeler"]],
    )
