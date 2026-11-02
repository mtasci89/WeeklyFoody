"""Tavily ile internet araması (Google'sız).

Kullanıcı: "Google hiç kullanma; Groq ve Tavily ile ilerleyelim." Tarif araştırması,
günlük keşif ve asistanın web_ara aracı buradan arar. Ücretsiz katman ayda ~1.000
arama (temel arama 1 kredi); bu yüzden bir çağrıda en fazla birkaç sorgu atılır.
Sonuç, sayfaların okunan metniyle birlikte (metin, ["başlık: bağlantı"]) döner;
tarifi yapılandırma ve kaynak denetimi bu metne dayanır.
"""
from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

URL = "https://api.tavily.com/search"
PAGE_CHARS = 2500
ROLE_TEXT = {"main": "ana yemek", "side": "yan yemek", "soup": "çorba", "salad": "salata", "meze": "meze"}


class TavilyError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def queries_for(prompt: str, limit: int = 3) -> list[str]:
    """Uzun araştırma isteminden kısa arama sorguları üretir."""
    request = ""
    match = re.search(r"İSTEK:\n(.+?)(?:\n[A-ZÇĞİÖŞÜ ]+:\n|\Z)", prompt, re.S)
    if match:
        request = " ".join(match.group(1).split())[:80]
    roles = re.findall(r"rol=(\w+)", prompt)
    if roles:
        seen = list(dict.fromkeys(roles))
        queries = [f"sıradışı ev yapımı {ROLE_TEXT.get(r, r)} tarifi malzemeler hazırlanışı {request}".strip() for r in seen]
        return queries[:limit]
    if "İnternette ara" in prompt:  # günlük keşif
        month = re.search(r"\(\d{4}-\d{2}-\d{2}, (\w+)\)", prompt)
        season = f" {month.group(1)}" if month else ""
        return [f"yeni popüler akşam yemeği tarifi{season}", f"sıradışı yan yemek tarifi{season}",
                f"ev yapımı meze tarifi{season}"][:limit]
    return [" ".join(prompt.split())[:350]]


class TavilySearch:
    def __init__(self, api_key: str, timeout: float = 30.0, client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def query(self, query: str, max_results: int = 4, raw: bool = True) -> list[dict]:
        response = await self.client.post(
            URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"query": query[:380], "search_depth": "basic", "max_results": max_results,
                  "include_raw_content": raw, "include_answer": False},
        )
        if response.status_code != 200:
            raise TavilyError(f"Tavily araması reddedildi ({response.status_code})", response.status_code)
        return list(response.json().get("results") or [])

    async def search(self, queries: list[str], max_results: int = 4) -> tuple[str, list[str]]:
        """Sorguları çalıştırır; tekrar eden sayfaları birleştirir."""
        pages, sources, seen = [], [], set()
        for query in queries:
            for row in await self.query(query, max_results=max_results):
                url = str(row.get("url") or "")
                if not url.startswith("https://") or url in seen:
                    continue
                seen.add(url)
                title = str(row.get("title") or "kaynak").strip()
                body = str(row.get("raw_content") or row.get("content") or "").strip()
                pages.append(f"### {title}\n{url}\n{body[:PAGE_CHARS]}")
                sources.append(f"{title}: {url}")
        logger.info("tavily_search queries=%s pages=%s", len(queries), len(pages))
        return "\n\n".join(pages), sources
