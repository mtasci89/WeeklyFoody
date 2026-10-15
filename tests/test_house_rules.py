from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.agent.rules import HouseRules
from app.db.models import Base
from app.db.session import ensure_columns


@pytest.fixture()
def session_factory(db):
    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    return _Factory()


@pytest.fixture()
def house(session_factory):
    return HouseRules(session_factory)


# --- HouseRules ---------------------------------------------------------


def test_empty_document_has_no_rules(house):
    assert house.active() == []
    assert house.for_prompt() == ""


def test_add_appends_bullets_and_skips_duplicates(house):
    assert house.add("Balık kullanma")
    assert house.add("  - Protein   ağırlıklı olsun ")
    assert not house.add("balık KULLANMA")
    assert not house.add("   ")

    assert house.active() == ["Balık kullanma", "Protein ağırlıklı olsun"]
    assert house.read_raw() == "- Balık kullanma\n- Protein ağırlıklı olsun\n"


def test_rules_persist_in_the_database(db, house, session_factory):
    house.add("Balık kullanma")

    assert HouseRules(session_factory).active() == ["Balık kullanma"]


def test_comments_and_title_are_not_sent_to_the_agent(house):
    house.write_raw("# Ev kuralları\n<!--\n- Örnek kural\n-->\n- Balık kullanma\nAçıklama satırı\n")

    assert house.active() == ["Balık kullanma"]
    assert house.for_prompt() == "- Balık kullanma\nAçıklama satırı"


def test_remove_deletes_exact_bullet_but_not_commented_example(house):
    house.write_raw("<!--\n- Balık kullanma\n-->\n- Balık kullanma\n- Protein ağırlıklı olsun\n")

    assert house.remove("balık kullanma")
    assert not house.remove("olmayan kural")

    assert house.active() == ["Protein ağırlıklı olsun"]
    assert "<!--\n- Balık kullanma\n-->" in house.read_raw()


def test_replace_rewrites_whole_list(house):
    house.add("Eski kural")

    saved = house.replace("Balık kullanma\n\n- Her akşam 3 farklı yemek olsun\nbalık kullanma\n")

    assert saved == ["Balık kullanma", "Her akşam 3 farklı yemek olsun"]
    assert house.active() == saved
    assert house.replace("") == []
    assert house.active() == []


# --- ajan baglami ------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_context_reads_rules_fresh_each_turn(db, settings, session_factory):
    from app.agent.runner import MealPlannerAgent
    from app.agent.tools import MealAgentToolset

    agent = MealPlannerAgent(settings.model_copy(update={"agent_provider": "anthropic"}), session_factory, client=object())
    toolset = MealAgentToolset(settings, session_factory)

    assert "Ev kuralları" not in agent._context(toolset)

    HouseRules(session_factory).add("Balık kullanma")
    context = agent._context(toolset)

    assert "## Ev kuralları" in context
    assert "- Balık kullanma" in context
    # Kurallar planin onunde gelir
    assert context.index("Ev kuralları") < context.index("## Aktif plan")


# --- sema guncellemesi ---------------------------------------------------


def test_ensure_columns_adds_nutrition_to_an_old_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE recipes (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text("INSERT INTO recipes (id, name) VALUES (1, 'Pilav')"))

    ensure_columns(engine)
    ensure_columns(engine)  # ikinci kez calismasi zararsiz

    columns = {c["name"] for c in inspect(engine).get_columns("recipes")}
    assert {"calories_per_serving", "protein_g_per_serving"} <= columns
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM recipes")).scalar() == "Pilav"
    engine.dispose()


# --- Telegram komutlari ------------------------------------------------


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, text: str, user_id: int):
        self.effective_message = FakeMessage(text)
        self.effective_user = type("U", (), {"id": user_id})()
        self.effective_chat = type("C", (), {"id": user_id, "type": "private"})()


@pytest.fixture()
def handlers(settings, monkeypatch):
    import app.bot.handlers as module

    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))

    class FakeBot:
        async def send_message(self, *args, **kwargs):
            pass

    yield module.TelegramHandlers(settings, FakeBot())
    engine.dispose()


async def run(handlers, name, text, user_id=111):
    update = FakeUpdate(text, user_id)
    await getattr(handlers, name)(update, None)
    return update.effective_message.replies


@pytest.mark.asyncio
async def test_telegram_commands_manage_rules_without_the_model(handlers):
    assert "Henüz ev kuralı yok" in (await run(handlers, "rules", "/kurallar"))[0]

    assert "Kural eklendi" in (await run(handlers, "rule_add", "/kural_ekle Balık kullanma"))[0]
    assert "zaten var" in (await run(handlers, "rule_add", "/kural_ekle@FoodyBot balık kullanma"))[0]
    await run(handlers, "rule_add", "/kural_ekle Öğün başı 1000 kaloriyi geçmesin")

    listing = (await run(handlers, "rules", "/kurallar"))[0]
    assert "1. Balık kullanma" in listing
    assert "2. Öğün başı 1000 kaloriyi geçmesin" in listing

    assert "Kural silindi: Balık kullanma" in (await run(handlers, "rule_delete", "/kural_sil 1"))[0]
    assert "geçen bir kural yok" in (await run(handlers, "rule_delete", "/kural_sil domates"))[0]
    assert "Kural silindi" in (await run(handlers, "rule_delete", "/kural_sil kalori"))[0]
    assert "Henüz ev kuralı yok" in (await run(handlers, "rules", "/kurallar"))[0]


@pytest.mark.asyncio
async def test_kurallari_yaz_replaces_the_list_from_one_message(handlers):
    await run(handlers, "rule_add", "/kural_ekle Eski kural")

    reply = (await run(handlers, "rules_replace", "/kurallari_yaz\nBalık kullanma\nProtein ağırlıklı olsun"))[0]

    assert "1. Balık kullanma\n2. Protein ağırlıklı olsun" in reply
    assert "Eski kural" not in reply
    assert "Henüz ev kuralı yok" in (await run(handlers, "rules_replace", "/kurallari_yaz sil"))[0]
    assert "Tüm listeyi" in (await run(handlers, "rules_replace", "/kurallari_yaz"))[0]


@pytest.mark.asyncio
async def test_rule_commands_are_admin_only(handlers):
    reply = (await run(handlers, "rule_add", "/kural_ekle Balık kullanma", user_id=999))[0]

    assert "yalnızca admin" in reply
    assert "Henüz ev kuralı yok" in (await run(handlers, "rules", "/kurallar"))[0]
