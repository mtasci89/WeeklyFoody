from __future__ import annotations

from app.db.models import PreferenceType
from app.memory.preferences import PreferenceService
from app.memory.rules import MealRules


class HouseRules:
    """Ev kurallari: Telegram komutlari ve ajan araclari icin ortak giris.

    Tek kayit kaynagi `preferences` tablosudur (panel ve /preferences ile
    ayni kayitlar); yorumlama ve denetim `app.memory.rules.MealRules`te.
    Satirlar `PreferenceService.document()` bicimindedir: yumusak tercihler
    "Tercih: " onekiyle yazilir.
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def active(self) -> list[str]:
        with self.session_factory() as db:
            document = PreferenceService(db).document()
        return [line for line in document.splitlines() if line.strip()]

    def summary(self) -> list[str]:
        """Sistemin hangi kurali otomatik denetledigi, hangisini yalnizca ajana ilettigi."""
        with self.session_factory() as db:
            return MealRules.from_db(db).summary()

    def add(self, rule: str) -> tuple[bool, str]:
        """(eklendi_mi, aciklama). "Tercih: ..." yumusak tercih olarak eklenir."""
        text = " ".join(rule.split()).strip().lstrip("-* ").strip()
        kind = PreferenceType.HARD
        if text.casefold().startswith("tercih:"):
            kind, text = PreferenceType.SOFT, text.split(":", 1)[1].strip()
        if not text:
            return False, "Kural metni boş."
        with self.session_factory() as db:
            prefs = PreferenceService(db)
            if any(p.rule.casefold() == text.casefold() and p.type == kind for p in prefs.active()):
                return False, "Bu kural zaten var."
            try:
                prefs.add(text, kind, source="telegram")
            except ValueError as error:
                return False, str(error)
        return True, text

    def matching(self, phrase: str) -> list[str]:
        needle = phrase.casefold().strip()
        return [rule for rule in self.active() if needle and needle in rule.casefold()]

    def remove(self, line: str) -> bool:
        """`active()` satirlarindan birini birebir siler (gecmis korunur, kayit pasiflesir)."""
        kind, text = PreferenceType.HARD, line.strip()
        if text.startswith("Tercih: "):
            kind, text = PreferenceType.SOFT, text[len("Tercih: "):]
        with self.session_factory() as db:
            for pref in PreferenceService(db).active(kind):
                if pref.rule == text:
                    pref.active = False
                    db.commit()
                    return True
        return False

    def replace(self, text: str) -> list[str]:
        """Tum listeyi yeniden yazar; gecersiz/celisen kuralda ValueError."""
        with self.session_factory() as db:
            prefs = PreferenceService(db)
            prefs.replace_document(text, prefs.revision())
        return self.active()
