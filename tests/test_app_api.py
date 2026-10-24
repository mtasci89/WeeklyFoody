from __future__ import annotations

import base64
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import create_api_app
from app.api_tls import (
    connection_code,
    ensure_certificate,
    parse_connection_code,
    prepare,
    read_env_value,
    spki_pin,
)
from app.db.models import Base, Recipe, RecipeStatus, SessionState
from app.planner.service import MealPlannerService
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.nutrition import NutritionInput, save_nutrition
from app.recipes.service import RecipeService
from tests.conftest import seed_recipes

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def factory(settings):
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        seed_recipes(db)
    yield Session
    engine.dispose()


@pytest.fixture()
def api_settings(settings):
    return settings.model_copy(update={"app_api_token": TOKEN})


class FakeReply:
    def __init__(self, text, plan_session_id=None):
        self.text = text
        self.ok = True
        self.tool_calls = ["plan_kaydet(...)"]
        self.plan_session_id = plan_session_id


class FakeAgent:
    def __init__(self, plan_session_id=None):
        self.messages: list[str] = []
        self.plan_session_id = plan_session_id

        class Store:
            def history(self, chat_id):
                return [{"role": "user", "content": "selam"}, {"role": "assistant", "content": "merhaba"}]

        self.store = Store()

    async def reply(self, chat_id, message, images=None):
        self.messages.append(message)
        return FakeReply("Tamam, hazırladım.", self.plan_session_id)


@pytest.fixture()
def client(api_settings, factory):
    return TestClient(create_api_app(api_settings, factory, agent=FakeAgent()))


async def _plan(factory, settings):
    with factory() as db:
        session = await MealPlannerService(db, settings).create_or_get_weekly_session()
        return session.id


# --- erisim ----------------------------------------------------------------


def test_short_token_refuses_to_start(settings, factory):
    with pytest.raises(ValueError, match="APP_API_TOKEN"):
        create_api_app(settings.model_copy(update={"app_api_token": "kisa"}), factory)


def test_requests_without_the_right_token_are_rejected(client):
    assert client.get("/api/v1/durum").status_code == 401
    assert client.get("/api/v1/durum", headers={"Authorization": "Bearer yanlis"}).status_code == 401
    ok = client.get("/api/v1/durum", headers=AUTH)
    assert ok.status_code == 200
    assert ok.json()["ad"] == "Foody"


def test_no_docs_or_schema_are_exposed(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# --- menu --------------------------------------------------------------------


def test_menu_without_a_plan(client):
    body = client.get("/api/v1/menu", headers=AUTH).json()

    assert body["plan"] is None


@pytest.mark.asyncio
async def test_menu_lists_seven_days_with_roles_and_nutrition(client, factory, api_settings):
    await _plan(factory, api_settings)
    with factory() as db:
        for recipe in db.query(Recipe).all():
            save_nutrition(db, recipe, NutritionInput(calories_kcal=300, protein_g=20, source="t"))
        db.commit()

    plan = client.get("/api/v1/menu", headers=AUTH).json()["plan"]

    assert len(plan["gunler"]) == 7
    assert plan["gunler"][0]["gun"] == "Pazartesi"
    meal = plan["gunler"][0]["ogunler"][0]
    assert {"slot", "rol", "tarif_id", "tarif", "kcal", "protein", "tahmini"} <= meal.keys()
    assert meal["kcal"] == 300
    assert plan["gunler"][0]["toplam_kcal"] == 300 * len(plan["gunler"][0]["ogunler"])
    assert plan["onaylanabilir"] is True


@pytest.mark.asyncio
async def test_approving_twice_is_refused(client, factory, api_settings):
    await _plan(factory, api_settings)

    first = client.post("/api/v1/menu/onayla", headers=AUTH, json={"hafta": "gelecek_hafta"})
    second = client.post("/api/v1/menu/onayla", headers=AUTH, json={"hafta": "gelecek_hafta"})

    assert first.status_code == 200
    assert first.json()["plan"]["durum"] == SessionState.APPROVED.value
    assert first.json()["plan"]["onaylanabilir"] is False
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_swap_changes_one_meal_and_rejects_unknown_recipes(client, factory, api_settings):
    await _plan(factory, api_settings)
    plan = client.get("/api/v1/menu", headers=AUTH).json()["plan"]
    day = plan["gunler"][0]
    main = next(m for m in day["ogunler"] if m["rol"] == "Ana yemek")
    other = next(n for n in ("Fırında Tavuk", "Kuru Fasulye", "Izgara Köfte") if n != main["tarif"])

    ok = client.post("/api/v1/menu/degistir", headers=AUTH, json={"tarih": day["tarih"], "slot": main["slot"], "tarif": other})
    bad = client.post("/api/v1/menu/degistir", headers=AUTH, json={"tarih": day["tarih"], "slot": main["slot"], "tarif": "Yok Böyle"})

    assert ok.status_code == 200, ok.text
    swapped = next(m for m in ok.json()["plan"]["gunler"][0]["ogunler"] if m["slot"] == main["slot"])
    assert swapped["tarif"] == other and swapped["degisti"] is True
    assert bad.status_code == 422
    assert "kütüphanede yok" in bad.json()["detail"]


# --- tarifler -------------------------------------------------------------------


def test_recipe_list_search_and_detail_scaling(client):
    listed = client.get("/api/v1/tarifler", headers=AUTH, params={"q": "tavuk"}).json()["tarifler"]
    assert [r["ad"] for r in listed] == ["Fırında Tavuk"]

    detail = client.get(f"/api/v1/tarifler/{listed[0]['id']}", headers=AUTH, params={"kisi": 2}).json()
    assert detail["kisi"] == 2 and detail["porsiyon"] == 4
    assert {"miktar": "500 g", "ad": "tavuk", "not": ""} in detail["malzemeler"]
    assert client.get("/api/v1/tarifler/yok", headers=AUTH).status_code == 404


def test_candidates_can_be_approved_or_removed(client, factory):
    with factory() as db:
        service = RecipeService(db)
        for name in ("Tavuk Fajita", "Ton Balıklı Salata"):
            service.upsert_recipe(
                RecipeInput(name=name, status="candidate", ingredients=[IngredientInput(name="tavuk", quantity=1, unit="adet")])
            )

    candidates = client.get("/api/v1/tarifler", headers=AUTH, params={"durum": "aday"}).json()["tarifler"]
    by_name = {c["ad"]: c["id"] for c in candidates}
    assert set(by_name) == {"Tavuk Fajita", "Ton Balıklı Salata"}

    assert client.post(f"/api/v1/tarifler/{by_name['Tavuk Fajita']}/onayla", headers=AUTH).status_code == 200
    assert client.post(f"/api/v1/tarifler/{by_name['Tavuk Fajita']}/onayla", headers=AUTH).status_code == 409
    assert client.post(f"/api/v1/tarifler/{by_name['Ton Balıklı Salata']}/cikar", headers=AUTH).status_code == 200
    with factory() as db:
        assert db.get(Recipe, by_name["Tavuk Fajita"]).status == RecipeStatus.APPROVED
        assert db.get(Recipe, by_name["Ton Balıklı Salata"]).status == RecipeStatus.INACTIVE


# --- alisveris ve kurallar ---------------------------------------------------------


@pytest.mark.asyncio
async def test_shopping_list_is_grouped_by_category(client, factory, api_settings):
    assert client.get("/api/v1/alisveris", headers=AUTH).json()["gruplar"] == []
    await _plan(factory, api_settings)

    body = client.get("/api/v1/alisveris", headers=AUTH).json()

    assert body["hafta_baslangic"]
    first = body["gruplar"][0]
    assert first["kategori"] and first["kalemler"][0]["anahtar"] and first["kalemler"][0]["metin"]


def test_rules_can_be_added_listed_removed_and_replaced(client):
    added = client.post("/api/v1/kurallar", headers=AUTH, json={"kural": "Balık kullanma"}).json()
    assert added["eklendi"] and added["kurallar"] == ["Balık kullanma"]
    assert any("Yasaklanan" in line for line in added["ozet"])

    again = client.post("/api/v1/kurallar", headers=AUTH, json={"kural": "balık kullanma"}).json()
    assert not again["eklendi"]

    assert client.post("/api/v1/kurallar/sil", headers=AUTH, json={"kural": "Balık kullanma"}).json()["kurallar"] == []
    assert client.post("/api/v1/kurallar/sil", headers=AUTH, json={"kural": "Balık kullanma"}).status_code == 404

    replaced = client.put("/api/v1/kurallar", headers=AUTH, json={"metin": "Protein ağırlıklı olsun\nKalorilerini de yaz yanına"})
    assert set(replaced.json()["kurallar"]) == {"Protein ağırlıklı olsun", "Kalorilerini de yaz yanına"}
    conflict = client.put("/api/v1/kurallar", headers=AUTH, json={"metin": "Her öğünde 2 yemek olsun\nHer öğünde 3 yemek olsun"})
    assert conflict.status_code == 422


# --- asistan -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_and_discovery_go_through_the_agent(api_settings, factory):
    session_id = await _plan(factory, api_settings)
    agent = FakeAgent(plan_session_id=session_id)
    client = TestClient(create_api_app(api_settings, factory, agent=agent))
    client.post("/api/v1/kurallar", headers=AUTH, json={"kural": "Kalorilerini de yaz yanına"})

    chat = client.post("/api/v1/sohbet", headers=AUTH, json={"mesaj": "yeni menü hazırla"}).json()
    found = client.post("/api/v1/kesif", headers=AUTH, json={"konu": "pratik tavuk"}).json()
    history = client.get("/api/v1/sohbet", headers=AUTH).json()["mesajlar"]

    assert chat["metin"] == "Tamam, hazırladım." and chat["plan_degisti"] is True
    assert chat["kalori_ozeti"].startswith("🔥")
    assert agent.messages[0] == "yeni menü hazırla"
    assert "pratik tavuk" in agent.messages[1] and "tarif_ekle" in agent.messages[1]
    assert found["ok"] is True
    assert history == [{"kullanici": True, "metin": "selam"}, {"kullanici": False, "metin": "merhaba"}]


# --- sertifika ve baglanti kodu -----------------------------------------------------------


def test_certificate_pin_matches_the_spki_hash(tmp_path):
    cert, key = tmp_path / "c.crt", tmp_path / "c.key"

    assert ensure_certificate(cert, key, "152.67.69.25") is True
    assert ensure_certificate(cert, key, "152.67.69.25") is False
    assert oct(key.stat().st_mode)[-3:] == "600"

    der = subprocess.run(
        f"openssl x509 -pubkey -noout -in {cert} | openssl pkey -pubin -outform der | openssl dgst -sha256 -binary",
        shell=True, check=True, capture_output=True,
    ).stdout
    assert spki_pin(cert) == base64.b64encode(der).decode()
    text = subprocess.run(["openssl", "x509", "-noout", "-text", "-in", str(cert)], capture_output=True, text=True).stdout
    assert "IP Address:152.67.69.25" in text


def test_connection_code_round_trip():
    code = connection_code("https://1.2.3.4:8443/", "abc", "pin==")

    assert code.startswith("FOODY1.")
    assert parse_connection_code(code) == {"u": "https://1.2.3.4:8443", "t": "abc", "p": "pin=="}


def test_prepare_writes_env_once_and_keeps_other_settings(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=gizli\nAPP_API_ENABLED=false\n", encoding="utf-8")
    cert, key = tmp_path / "a.crt", tmp_path / "a.key"

    first = prepare(env, "https://152.67.69.25:8443", cert, key)
    token = read_env_value(env, "APP_API_TOKEN")
    second = prepare(env, "https://152.67.69.25:8443", cert, key)

    assert first["yeni_anahtar"] and first["yeni_sertifika"]
    assert not second["yeni_anahtar"] and not second["yeni_sertifika"]
    assert len(token) >= 40 and read_env_value(env, "APP_API_TOKEN") == token
    assert read_env_value(env, "TELEGRAM_BOT_TOKEN") == "gizli"
    assert read_env_value(env, "APP_API_ENABLED") == "true"
    assert env.read_text().count("APP_API_ENABLED") == 1
    assert "gizli" not in str(first) and token not in str(first)
    with pytest.raises(ValueError):
        prepare(env, "http://152.67.69.25:8443", cert, key)


# --- Telegram /uygulama ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_uygulama_command_sends_the_code_only_when_ready(settings, tmp_path, monkeypatch):
    from app.bot.handlers import TelegramHandlers

    class Message:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    class Update:
        def __init__(self):
            self.effective_message = Message()
            self.effective_user = type("U", (), {"id": settings.admin_telegram_user_id})()
            self.effective_chat = type("C", (), {"id": 1})()

    class Bot:
        async def send_message(self, *a, **k):
            pass

    not_ready = Update()
    await TelegramHandlers(settings, Bot()).app_code(not_ready, None)
    assert "hazır değil" in not_ready.effective_message.replies[0]

    cert, key = tmp_path / "x.crt", tmp_path / "x.key"
    ensure_certificate(cert, key, "1.2.3.4")
    ready_settings = settings.model_copy(update={
        "app_api_enabled": True, "app_api_public_url": "https://1.2.3.4:8443",
        "app_api_token": TOKEN, "app_api_cert": cert, "app_api_key": key,
    })
    ready = Update()
    await TelegramHandlers(ready_settings, Bot()).app_code(ready, None)

    code = ready.effective_message.replies[-1]
    assert parse_connection_code(code) == {"u": "https://1.2.3.4:8443", "t": TOKEN, "p": spki_pin(cert)}


def test_api_server_is_skipped_without_certificate_and_built_with_one(settings, tmp_path, caplog):
    import logging

    from app.main import _app_api_server

    caplog.set_level(logging.ERROR)
    enabled = settings.model_copy(update={
        "app_api_enabled": True, "app_api_token": TOKEN,
        "app_api_cert": tmp_path / "y.crt", "app_api_key": tmp_path / "y.key",
    })

    assert _app_api_server(settings, bot=None) is None  # kapali
    assert _app_api_server(enabled, bot=None) is None
    assert "sertifika yok" in caplog.text

    ensure_certificate(enabled.app_api_cert, enabled.app_api_key, "127.0.0.1")
    server = _app_api_server(enabled, bot=None)
    assert server is not None and server.config.ssl_certfile == str(enabled.app_api_cert)
