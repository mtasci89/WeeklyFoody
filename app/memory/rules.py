"""Shared, deterministic interpretation of persistent meal rules.

Unrecognised text remains available to the agent, with an explicit warning;
it is never described as a constraint that the application enforces.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.config import base_meal_slot


def normalize(text: str) -> str:
    return text.casefold().replace('i\u0307', 'i').translate(str.maketrans('çğıöşü', 'cgiosu'))


FOOD_GROUPS = {
    'balik': ('balik', 'balig', 'fish', 'somon', 'salmon', 'hamsi', 'levrek', 'cipura', 'uskumru', 'palamut', 'alabalik', 'sardalya', 'mezgit', 'lufer', 'ton baligi', 'tuna', 'anchovy', 'trout', 'seabass'),
    'tavuk': ('tavuk', 'chicken'),
    'kirmizi et': ('kirmizi et', 'beef', 'lamb', 'veal', 'dana', 'kuzu', 'kiyma', 'kusbasi'),
}


class RuleViolation(ValueError):
    pass


@dataclass
class MealRules:
    excluded: set[str] = field(default_factory=set)
    dishes_per_meal: int | None = None
    max_kcal: float | None = None
    show_calories: bool = False
    protein_priority: bool = False
    advisory: list[str] = field(default_factory=list)

    @classmethod
    def from_db(cls, db):
        from app.memory.preferences import PreferenceService
        prefs = PreferenceService(db)
        return cls.parse(prefs.hard_rules(), prefs.soft_rules())

    @classmethod
    def parse(cls, hard: list[str], soft: list[str] = ()) -> MealRules:
        result = cls()
        counts = set()
        caps = []
        for rule, strict in [(r, True) for r in hard] + [(r, False) for r in soft]:
            text = normalize(rule).strip(' .!').replace('kalroi', 'kalori')
            if re.fullmatch(r'(?:bundan sonra |artik |asla )*(.+?)\s+(?:kullanma|onerme|olmasin|yasak|yeme)', text):
                food = re.fullmatch(r'(?:bundan sonra |artik |asla )*(.+?)\s+(?:kullanma|onerme|olmasin|yasak|yeme)', text)[1].strip()
                if strict:
                    for item in re.split(r'\s+ve\s+|,\s*', food):
                        item = re.sub(r'\b(?:hic|kesinlikle|asla)\b', '', item).strip()
                        if item:
                            result.excluded.update(FOOD_GROUPS.get(item, (item,)))
                else:
                    result.advisory.append(rule)
                continue
            english = re.fullmatch(r'(?:avoid|exclude|do not suggest)\s+(.+)', text)
            if english and strict:
                food = english[1].strip()
                result.excluded.update(FOOD_GROUPS.get(food, (food,)))
                continue
            count_text = text
            for word, number in [('bir',1),('iki',2),('uc',3),('dort',4),('bes',5),('alti',6)]:
                count_text = re.sub(r'\b'+word+r'\b', str(number), count_text)
            count = re.fullmatch(r'(?:(?:her )?ogunde |ogun basi |her ogun )?(\d+)\s+(?:farkli )?(?:yemek|cesit)(?: olsun)?', count_text)
            if count and strict:
                value = int(count[1])
                if not 1 <= value <= 6:
                    raise RuleViolation('Öğün başına yemek sayısı 1 ile 6 arasında olmalı.')
                counts.add(value)
                continue
            cap = re.fullmatch(r'(?:(?:bir |1 )?kisi (?:icin |basi(?:na)? )?)?(?:her )?ogun(?: basi| basina|de)?\s+(?:kalori(?:si)?\s+)?(?:en fazla\s+)?(\d+(?:[.,]\d+)?)\s*(?:kcal|kalori)?(?:[\s\x27’]*(?:yi|i|u|yu|nin|in))?\s*(?:gecmesin|asmasin|altinda olsun)?', text)
            if cap and strict:
                value = float(cap[1].replace(',', '.'))
                if value <= 0:
                    raise RuleViolation('Öğün kalori sınırı sıfırdan büyük olmalı.')
                caps.append(value)
                result.show_calories = True
                continue
            if re.fullmatch(r'(?:kalori(?:leri|lerini|sini|lerini de)?|kalorileri de)\s+(?:yaz(?: yanina)?|goster)(?: yanina)?', text):
                result.show_calories = True
                continue
            if re.fullmatch(r'protein (?:agirlikli|oncelikli|agirlikli olsun|oncelikli olsun)', text):
                result.protein_priority = True
                continue
            result.advisory.append(rule)
        if len(counts) > 1:
            raise RuleViolation('Yemek sayısı kuralları çelişiyor; tek bir öğün başına sayı bırakın.')
        result.dishes_per_meal = next(iter(counts), None)
        result.max_kcal = min(caps) if caps else None
        return result

    def excludes(self, recipe) -> bool:
        text = normalize(' '.join([recipe.name, recipe.protein_type or '', *(recipe.aliases or []), *(recipe.tags or []), *(i.ingredient.name for i in recipe.ingredients)]))
        return any(re.search(r'(?<!\w)' + re.escape(term) + r'(?:li|lu|i|u|a|e|in|un)?(?!\w)', text) for term in self.excluded)

    def settings_for_plan(self, settings):
        if self.dishes_per_meal is None:
            return settings
        # Keep a main, then a salad/meze, then a side; more dishes add mezes.
        roles = ['main', 'meze', 'side'][:self.dishes_per_meal]
        roles += ['meze'] * max(0, self.dishes_per_meal - 3)
        return settings.model_copy(update={'meal_course_roles': roles})

    def summary(self) -> list[str]:
        lines = []
        if self.excluded:
            lines.append('Yasaklanan içerikler plan kaydedilirken kontrol edilir.')
        if self.dishes_per_meal:
            lines.append(f'Her öğünde {self.dishes_per_meal} farklı yemek zorunlu.')
        if self.max_kcal is not None:
            lines.append(f'Kişi başı öğün toplamı en fazla {self.max_kcal:g} kcal; kalori verisi eksikse plan kaydedilmez.')
        if self.show_calories:
            lines.append('Menüde kişi başı kalori gösterilir; eksik değerler belirtilir.')
        if self.protein_priority:
            lines.append('Protein önceliği: kayıtlı protein miktarı seçim puanını artırır; eksikse yalnızca protein kaynağı türü kullanılır.')
        lines += [f'Yalnızca ajana iletilir, otomatik denetim yok: {r}' for r in self.advisory]
        return lines

    def validate(self, rows: list[tuple[date, str, object]], expected_meals=()) -> None:
        groups = defaultdict(list)
        for day, slot, recipe in rows:
            if self.excludes(recipe):
                raise RuleViolation(f'Kalıcı yasakla çelişen tarif: {recipe.name}.')
            groups[day, base_meal_slot(slot)].append(recipe)
        if self.dishes_per_meal:
            for key in set(groups) | set(expected_meals):
                recipes = groups[key]
                if len(recipes) != self.dishes_per_meal or len({r.id for r in recipes}) != self.dishes_per_meal:
                    raise RuleViolation(f'{key[0]} {key[1]}: her öğünde {self.dishes_per_meal} farklı yemek olmalı.')
        if self.max_kcal is not None:
            for (day, meal), recipes in groups.items():
                missing = [r.name for r in recipes if not r.nutrition or r.nutrition.calories_kcal is None]
                if missing:
                    raise RuleViolation('Kalori sınırı denetlenemiyor; porsiyon başına kalori bilgisi eksik: ' + ', '.join(missing))
                total = sum(r.nutrition.calories_kcal for r in recipes)
                if total > self.max_kcal:
                    raise RuleViolation(f'{day} {meal}: kişi başı {total:g} kcal, {self.max_kcal:g} kcal sınırını aşıyor.')


def session_rows(session):
    return [(i.date, i.meal_slot, i.recipe) for i in session.meal_plan.items]


def validate_session(db, session, settings):
    from app.planner.dates import week_dates
    rules = MealRules.from_db(db)
    rules.validate(session_rows(session), [(d, base) for d in week_dates(session.week_start) for base in settings.meal_slots])
