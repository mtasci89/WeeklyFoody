"""Foody uygulamasinin test ornekleri: gercek API'nin cevaplari.

Android testleri (`android/app/src/test/resources/ornek/*.json`) bu dosyalari
okur; `tests/test_app_contract.py` API'nin hala ayni bicimi verdigini denetler.
API cevabi degisirse ornekleri yeniden uret:

    python -m tests.app_samples android/app/src/test/resources/ornek
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

TOKEN = "o" * 40


class _Reply:
    text = "Gelecek hafta için menüyü hazırladım. Salı'yı hafif tuttum."
    ok = True
    tool_calls = ["plan_hazirla(hafta=gelecek_hafta)", "plan_kaydet(21 ogun)"]

    def __init__(self, plan_session_id):
        self.plan_session_id = plan_session_id


class _Agent:
    def __init__(self, plan_session_id, settings=None, session_factory=None):
        self.plan_session_id = plan_session_id
        self.settings = settings
        self.session_factory = session_factory

        class Store:
            def history(self, chat_id):
                return [
                    {"role": "user", "content": "Gelecek hafta için menü hazırla"},
                    {"role": "assistant", "content": _Reply.text},
                ]

        self.store = Store()

    async def reply(self, chat_id, message, images=None, timeout=None, channel="telegram"):
        if message == DEGISTIR and self.session_factory is not None:
            # Gercek araclarla bir degisiklik: uygulama "degisenler" kartini
            # gercek bir cevapla sinasin.
            from app.agent.tools import MealAgentToolset

            toolset = MealAgentToolset(self.settings, self.session_factory)
            tools = {t.name: t for t in toolset.build()}
            plan = toolset._resolve_session(self.session_factory(), "aktif")
            tuesday = sorted({i.date for i in plan.meal_plan.items})[1]
            await tools["ogun_degistir"].call(
                {"tarih": tuesday.isoformat(), "yeni_tarif": "Izgara Köfte", "gerekce": "ornek",
                 "ogun_slotu": "dinner_main"}
            )
            await tools["ogun_cikar"].call({"tarih": "HAFTA", "tarif_veya_slot": "Çoban Salata"})
        return _Reply(self.plan_session_id)


DEGISTIR = "Salı'daki balığı köfte yap, çoban salatayı çıkar"


def build_samples(workdir: Path) -> dict[str, object]:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.agent.rules import HouseRules
    from app.api import create_api_app
    from app.config import Settings
    from app.db.models import Base, Recipe
    from app.planner.service import MealPlannerService
    from app.recipes.importer import IngredientInput, RecipeInput
    from app.recipes.nutrition import NutritionInput, save_nutrition
    from app.recipes.service import RecipeService
    from tests.conftest import seed_recipes

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{workdir / 'ornek.db'}",
        admin_telegram_user_id=1,
        meal_slots=["dinner"],
        llm_provider="rule",
        app_api_token=TOKEN,
    )
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        seed_recipes(db)
        RecipeService(db).upsert_recipe(
            RecipeInput(
                name="Tavuk Fajita", status="candidate", category="main", source="https://ornek.example/fajita",
                instructions="Tavuğu baharatla soteleyin, lavaşa sarın.",
                ingredients=[IngredientInput(name="tavuk göğsü", quantity=600, unit="g")],
            )
        )
        for index, recipe in enumerate(db.query(Recipe).order_by(Recipe.name).all()):
            if index % 4:  # bazi tariflerin degeri bilinmesin
                save_nutrition(db, recipe, NutritionInput(calories_kcal=250 + 30 * index, protein_g=8 + index, source="ornek"))
        db.commit()
        session = asyncio.run(MealPlannerService(db, settings).create_or_get_weekly_session())
        session_id = session.id
    HouseRules(Session).add("Balık kullanma")
    HouseRules(Session).add("Kalorilerini de yaz yanına")
    HouseRules(Session).add("Mutfakta az bulaşık çıksın")

    client = TestClient(create_api_app(settings, Session, agent=_Agent(session_id, settings, Session)))
    auth = {"Authorization": f"Bearer {TOKEN}"}
    library = client.get("/api/v1/tarifler", headers=auth).json()
    tavuk = next(r for r in library["tarifler"] if r["ad"] == "Fırında Tavuk")
    samples = {
        "durum": client.get("/api/v1/durum", headers=auth).json(),
        "menu": client.get("/api/v1/menu", headers=auth).json(),
        "menu_bos": {"kalori_goster": False, "kalori_siniri": None, "kisi": 4, "plan": None},
        "tarifler": library,
        "adaylar": client.get("/api/v1/tarifler", headers=auth, params={"durum": "aday"}).json(),
        "tarif": client.get(f"/api/v1/tarifler/{tavuk['id']}", headers=auth, params={"kisi": 2}).json(),
        "alisveris": client.get("/api/v1/alisveris", headers=auth).json(),
        "menu_tarifler": client.get("/api/v1/menu/tarifler", headers=auth, params={"kisi": 4}).json(),
        "kurallar": client.get("/api/v1/kurallar", headers=auth).json(),
        "sohbet": client.post("/api/v1/sohbet", headers=auth, json={"mesaj": "menü"}).json(),
        "sohbet_gecmisi": client.get("/api/v1/sohbet", headers=auth).json(),
        "hata": client.post("/api/v1/kurallar/sil", headers=auth, json={"kural": "olmayan"}).json(),
    }
    # Arka plan isi: baslat, sonra bitene kadar sor (TestClient baglami acik kalmali).
    with client:
        started = client.post("/api/v1/sohbet/baslat", headers=auth, json={"mesaj": DEGISTIR}).json()
        samples["is_baslat"] = {**started, "is": "ornek-is"}
        for _ in range(200):
            body = client.get(f"/api/v1/is/{started['is']}", headers=auth).json()
            if body["durum"] != "calisiyor":
                break
            time.sleep(0.02)
        samples["is_bitti"] = {**body, "is": "ornek-is"}
        samples["is_suruyor"] = {"is": "ornek-is", "durum": "calisiyor", "sonuc": None, "hata": None}
    engine.dispose()
    return samples


def main(target: str) -> None:
    out = Path(target)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in build_samples(Path(tmp)).items():
            (out / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{name}.json")


if __name__ == "__main__":
    main(sys.argv[1])
