from __future__ import annotations

import re

from sqlalchemy import select

from app.db.models import HouseRulesDocument

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")


def _clean(rule: str) -> str:
    return " ".join(rule.split()).strip().lstrip("-* ").strip()


class HouseRules:
    """Kullanicinin kalici ev kurallari: CLAUDE.md gibi tek bir markdown belge.

    Veritabaninda durur (dosyada degil): bot sunucuda calisirken telefondan
    yalnizca Telegram uzerinden duzenlenebilir ve yeniden kurulumda
    kaybolmamasi gerekir. Her istekte taze okunur; ekleme/silme bir sonraki
    mesajda gecerlidir.
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def _row(self, db) -> HouseRulesDocument | None:
        return db.scalar(select(HouseRulesDocument).order_by(HouseRulesDocument.id).limit(1))

    def read_raw(self) -> str:
        with self.session_factory() as db:
            row = self._row(db)
            return row.text if row else ""

    def write_raw(self, text: str) -> None:
        with self.session_factory() as db:
            row = self._row(db)
            if row is None:
                db.add(HouseRulesDocument(text=text))
            else:
                row.text = text
            db.commit()

    def _visible(self) -> str:
        return _COMMENT.sub("", self.read_raw())

    def active(self) -> list[str]:
        """Madde isaretli satirlar: listeleme ve silme icin."""
        return [m.group(1) for line in self._visible().splitlines() if (m := _BULLET.match(line))]

    def for_prompt(self) -> str:
        """Ajana gidecek metin: yorumlar ve ana baslik ayiklanmis, kural yoksa bos."""
        lines = [line for line in self._visible().splitlines() if not line.startswith("# ")]
        return "\n".join(lines).strip()

    def add(self, rule: str) -> bool:
        """Kurali madde olarak sona ekler. Ayni kural zaten varsa eklemez."""
        cleaned = _clean(rule)
        if not cleaned:
            return False
        if any(existing.casefold() == cleaned.casefold() for existing in self.active()):
            return False
        raw = self.read_raw()
        if raw and not raw.endswith("\n"):
            raw += "\n"
        self.write_raw(raw + f"- {cleaned}\n")
        return True

    def replace(self, text: str) -> list[str]:
        """Tum listeyi yeniden yazar. Her bos olmayan satir bir kural olur;
        madde isareti olmayan satirlara eklenir. Kaydedilen kurallari dondurur."""
        rules: list[str] = []
        for line in text.splitlines():
            cleaned = _clean(line)
            if cleaned and cleaned.casefold() not in {r.casefold() for r in rules}:
                rules.append(cleaned)
        self.write_raw("".join(f"- {rule}\n" for rule in rules))
        return rules

    def matching(self, phrase: str) -> list[str]:
        needle = phrase.casefold().strip()
        return [rule for rule in self.active() if needle and needle in rule.casefold()]

    def remove(self, rule: str) -> bool:
        """Tam olarak bu metne sahip madde satirini siler (yorumlara dokunmaz)."""
        target = rule.casefold().strip()
        raw = self.read_raw()
        kept, removed = [], False
        protected = [(m.start(), m.end()) for m in _COMMENT.finditer(raw)]
        offset = 0
        for line in raw.splitlines(keepends=True):
            start = offset
            offset += len(line)
            inside_comment = any(a <= start < b for a, b in protected)
            match = _BULLET.match(line.rstrip("\n"))
            if not removed and not inside_comment and match and match.group(1).casefold() == target:
                removed = True
                continue
            kept.append(line)
        if removed:
            self.write_raw("".join(kept))
        return removed
