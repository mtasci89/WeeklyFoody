"""Shared, deterministic interpretation of persistent meal rules.

Unrecognised text remains available to the agent, with an explicit warning;
it is never described as a constraint that the application enforces.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.config import base_meal_slot, is_weekly_slot


def normalize(text: str) -> str:
    return text.casefold().replace('i\u0307', 'i').translate(str.maketrans('çğıöşü', 'cgiosu'))


FOOD_GROUPS = {
    'balik': ('balik', 'balig', 'fish', 'somon', 'salmon', 'hamsi', 'levrek', 'cipura', 'uskumru', 'palamut', 'alabalik', 'sardalya', 'mezgit', 'lufer', 'ton baligi', 'tuna', 'anchovy', 'trout', 'seabass'),
    'tavuk': ('tavuk', 'chicken'),
    'kirmizi et': ('kirmizi et', 'beef', 'lamb', 'veal', 'dana', 'kuzu', 'kiyma', 'kusbasi'),
}


_NUMBER_WORDS = [('bir', 1), ('iki', 2), ('uc', 3), ('dort', 4), ('bes', 5), ('alti', 6), ('yedi', 7)]
_NEW_WORDS = r'(?:yeni|siradisi|degisik|denenmemis|ilginc|farkli)'


def parse_weekly_mezes(text: str) -> int | None:
    """"mezeler günlere bölünmesin" -> -1, "haftada 4 meze olsun" -> 4,
    "mezeler günlere dağıtılsın" -> 0. `text` normalize edilmiş olmalı."""
    for word, number in _NUMBER_WORDS:
        text = re.sub(r'\b' + word + r'\b', str(number), text)
    if re.fullmatch(
        r'mezeler(?:i)?\s+(?:her\s+)?(?:gunlere|ogunlere|gune)\s+(?:dagitilsin|bolunsun|ayrilsin|dagit|bol|koy)',
        text,
    ):
        return 0
    count = re.fullmatch(
        r'(?:haftada|haftalik|her\s+hafta)\s+(?:en\s+az\s+)?(\d+)\s+(?:tane\s+|cesit\s+|farkli\s+)?meze'
        r'(?:\s+(?:olsun|hazirla|hazirlansin|yap|yeter|yeterli))?',
        text,
    )
    if count:
        value = int(count[1])
        if not 0 <= value <= 10:
            raise RuleViolation('Haftalık meze sayısı 0 ile 10 arasında olmalı.')
        return value
    if re.fullmatch(
        r'(?:mezeler(?:i)?\s+)?(?:(?:gunlere|ogunlere|gun\s+gun|gunlere\s+gore)\s+)?'
        r'(?:bolunmesin|bolme|dagitilmasin|dagitma|ayrilmasin|ayirma|ayrismasin)'
        r'(?:\s*,?\s*haftalik\s+(?:ayri\s+)?(?:liste\s+)?olsun)?',
        text,
    ) and 'meze' in text:
        return -1
    if re.fullmatch(r'mezeler(?:i)?\s+haftalik(?:\s+(?:ayri\s+)?(?:bir\s+)?(?:liste|listede))?(?:\s+(?:olsun|hazirlansin|tut))?', text):
        return -1
    return None


def parse_new_dishes(text: str) -> int | None:
    """"her hafta 2 sıradışı yemek olsun" -> 2, "yeni yemek ekleme" -> 0.

    `text` normalize edilmiş olmalı. "farkli" yalnızca hafta bağlamında sayılır;
    yoksa "öğünde 2 farklı yemek" kuralıyla karışır.
    """
    for word, number in _NUMBER_WORDS:
        text = re.sub(r'\b' + word + r'\b', str(number), text)
    off = re.fullmatch(
        r'(?:(?:her hafta|haftada|haftalik menuye?)\s+)?' + _NEW_WORDS
        + r'\s+(?:yemek|tarif)(?:ler)?(?:i|e)?\s+(?:olmasin|ekleme|eklenmesin|koyma|istemiyorum|onerme)',
        text,
    )
    if off:
        return 0
    match = re.fullmatch(
        r'(?P<week>(?:her hafta|haftada|her haftaki menude|haftalik menude|haftalik menuye)\s+)?'
        r'(?:(?:menuye|menude)\s+)?(?:en az\s+)?(?P<n>\d+)\s+(?:tane\s+)?'
        r'(?P<adj>' + _NEW_WORDS + r')(?:\s+(?:ve|ya da|veya)\s+' + _NEW_WORDS + r')?'
        r'\s+(?:yemek|tarif)(?:ler)?'
        r'(?:\s+(?:olsun|ekle|eklensin|koy|konsun|dene|denensin|gelsin|oner|onersin))?',
        text,
    )
    if not match or (match['adj'] == 'farkli' and not match['week']):
        return None
    value = int(match['n'])
    if not 0 <= value <= 7:
        raise RuleViolation('Haftalık yeni yemek sayısı 0 ile 7 arasında olmalı.')
    return value


class RuleViolation(ValueError):
    pass


@dataclass
class MealRules:
    excluded: set[str] = field(default_factory=set)
    dishes_per_meal: int | None = None
    max_kcal: float | None = None
    show_calories: bool = False
    protein_priority: bool = False
    # Her hafta menüye girecek, kütüphanede olmayan yeni yemek sayısı.
    # None: kural yok, ayardaki varsayılan (WEEKLY_NEW_DISHES) geçerli.
    new_dishes: int | None = None
    # Haftalık meze listesi: None kural yok (ayar geçerli), -1 "haftalık olsun"
    # (sayı ayardan), 0 mezeler günlere dağıtılır, N haftada N meze.
    weekly_mezes: int | None = None
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
            mezes = parse_weekly_mezes(text)
            if mezes is not None:
                result.weekly_mezes = mezes
                continue
            novelty = parse_new_dishes(text)
            if novelty is not None:
                result.new_dishes = novelty
                continue
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
            count = re.fullmatch(r'(?:(?:her )?ogunde |ogun basi |her ogun |(?:her )?aksam(?:lari)? )?(\d+)\s+(?:farkli )?(?:yemek|cesit)(?: olsun)?', count_text)
            if count and strict:
                value = int(count[1])
                if not 1 <= value <= 6:
                    raise RuleViolation('Öğün başına yemek sayısı 1 ile 6 arasında olmalı.')
                counts.add(value)
                continue
            cap = re.fullmatch(r'(?:(?:bir |1 )?kisi (?:icin |basi(?:na)? )?)?(?:her )?(?:bir |1 )?ogun(?: basi| basina|de)?\s+(?:kalori(?:si)?\s+)?(?:en fazla\s+)?(\d+(?:[.,]\d+)?)\s*(?:kcal|kalori)?(?:[\s\x27’]*(?:yi|i|u|yu|nin|in))?\s*(?:gecmesin|asmasin|altinda olsun)?', text)
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
            # Serbest yazimlar: "her yemegin yanina kalorisini yaz", "gunluk
            # kaloriyi de goster". Olumsuzu ("yazilmasin", "gosterme") sayilmaz.
            if ('kalori' in text and re.search(r'\b(?:yaz|goster|belirt|ekle)', text)
                    and not re.search(r'(?:yazma|yazilmasin|gosterme|gosterilmesin|belirtme|ekleme|istemiyorum)', text)):
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

    def weekly_meze_target(self, settings) -> int:
        """Haftalık meze listesinin uzunluğu; 0 ise mezeler günlere dağıtılır."""
        if self.weekly_mezes is None:
            return settings.weekly_meze_count
        if self.weekly_mezes < 0:
            return settings.weekly_meze_count or 4
        return self.weekly_mezes

    def new_dish_target(self, settings) -> int:
        """Bu hafta menüye girecek yeni yemek sayısı: ev kuralı yoksa ayar."""
        return self.new_dishes if self.new_dishes is not None else settings.weekly_new_dishes

    def excludes(self, recipe) -> bool:
        text = normalize(' '.join([recipe.name, recipe.protein_type or '', *(recipe.aliases or []), *(recipe.tags or []), *(i.ingredient.name for i in recipe.ingredients)]))
        return any(re.search(r'(?<!\w)' + re.escape(term) + r'(?:li|lu|i|u|a|e|in|un)?(?!\w)', text) for term in self.excluded)

    def settings_for_plan(self, settings):
        weekly = self.weekly_meze_target(settings) > 0
        if self.dishes_per_meal is None:
            if not weekly:
                return settings
            # Mezeler haftalık listede: günlük şekilden çıkar.
            roles = [r for r in settings.meal_course_roles if r != 'meze'] or ['main']
            return settings.model_copy(update={'meal_course_roles': roles})
        if weekly:
            roles = ['main', 'side', 'soup'][:self.dishes_per_meal]
            roles += ['side'] * max(0, self.dishes_per_meal - 3)
        else:
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
        if self.weekly_mezes is not None:
            if self.weekly_mezes == 0:
                lines.append('Mezeler günlere dağıtılır.')
            elif self.weekly_mezes > 0:
                lines.append(f'Mezeler günlere bölünmez: haftada {self.weekly_mezes} mezelik ayrı liste.')
            else:
                lines.append('Mezeler günlere bölünmez: haftalık ayrı liste.')
        if self.new_dishes:
            lines.append(f'Her hafta menüde en az {self.new_dishes} yeni (kütüphanede olmayan) yemek olur.')
        elif self.new_dishes == 0:
            lines.append('Haftalık menüye yeni yemek eklenmez; yalnızca kütüphaneden seçilir.')
        if self.protein_priority:
            lines.append('Protein önceliği: kayıtlı protein miktarı seçim puanını artırır; eksikse yalnızca protein kaynağı türü kullanılır.')
        lines += [f'Yalnızca ajana iletilir, otomatik denetim yok: {r}' for r in self.advisory]
        return lines

    def validate(self, rows: list[tuple[date, str, object]], expected_meals=()) -> None:
        groups = defaultdict(list)
        for day, slot, recipe in rows:
            if self.excludes(recipe):
                raise RuleViolation(f'Kalıcı yasakla çelişen tarif: {recipe.name}.')
            if is_weekly_slot(slot):
                continue  # haftalık meze listesi hiçbir öğüne sayılmaz
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
    # Bos birakilan gunler (disarida yemek) serbest; yazilan her ogun kurala uymali.
    # Otomatik planlayicinin her gunu doldurmasini PlanValidator ayrica sart kosar.
    MealRules.from_db(db).validate(session_rows(session))
