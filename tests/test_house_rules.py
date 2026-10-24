from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.rules import HouseRules
from app.db.models import Base


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


def test_empty_rules(house):
    assert house.active() == []


def test_add_stores_hard_and_soft_rules_and_skips_duplicates(db, house):
    from app.memory.preferences import PreferenceService

    assert house.add("Balık kullanma") == (True, "Balık kullanma")
    assert house.add("  - Tercih:  Protein   ağırlıklı olsun ")[0]
    assert house.add("balık KULLANMA") == (False, "Bu kural zaten var.")
    assert house.add("   ")[0] is False

    assert PreferenceService(db).hard_rules() == ["Balık kullanma"]
    assert PreferenceService(db).soft_rules() == ["Protein ağırlıklı olsun"]
    assert set(house.active()) == {"Balık kullanma", "Tercih: Protein ağırlıklı olsun"}


def test_add_rejects_contradicting_rules(house):
    assert house.add("Her öğünde 3 farklı yemek olsun")[0]

    added, detail = house.add("Her öğünde 2 farklı yemek olsun")

    assert not added
    assert "çelişiyor" in detail


def test_summary_says_what_the_system_enforces(house):
    house.add("Balık kullanma")
    house.add("Mutfakta az bulaşık çıksın")

    summary = "\n".join(house.summary())

    assert "Yasaklanan içerikler" in summary
    assert "otomatik denetim yok: Mutfakta az bulaşık çıksın" in summary


def test_remove_deactivates_exact_rule(db, house):
    from app.db.models import Preference

    house.add("Balık kullanma")
    house.add("Tercih: Protein ağırlıklı olsun")

    assert house.remove("Tercih: Protein ağırlıklı olsun")
    assert not house.remove("olmayan kural")

    assert house.active() == ["Balık kullanma"]
    # Gecmis korunur: kayit silinmez, pasiflesir
    assert db.query(Preference).count() == 2


def test_replace_rewrites_whole_list(house):
    house.add("Eski kural")

    saved = house.replace("Balık kullanma\n\n- Her öğünde 3 farklı yemek olsun\n")

    assert set(saved) == {"Balık kullanma", "Her öğünde 3 farklı yemek olsun"}
    assert house.replace("") == []


def test_replace_keeps_old_list_on_invalid_input(house):
    house.add("Balık kullanma")

    with pytest.raises(ValueError):
        house.replace("Her öğünde 2 farklı yemek olsun\nHer öğünde 3 farklı yemek olsun")

    assert house.active() == ["Balık kullanma"]


def test_delete_preference_ignores_empty_query(db, house):
    from app.memory.preferences import PreferenceService

    house.add("Balık kullanma")

    assert PreferenceService(db).delete("   ") is False
    assert house.active() == ["Balık kullanma"]


@pytest.mark.asyncio
async def test_dish_count_rule_allows_an_empty_day_but_not_a_short_one(db, settings, session_factory):
    from app.agent.tools import MealAgentToolset
    from app.planner.dates import next_week_start, week_dates

    HouseRules(session_factory).add("Her öğünde 1 farklı yemek olsun")
    toolset = MealAgentToolset(settings, session_factory)
    plan_kaydet = next(t for t in toolset.build() if t.name == "plan_kaydet")
    days = week_dates(next_week_start(timezone=settings.timezone))

    # Hafta sonu disarida: bos gunler kurali ihlal etmez
    mains = ["Fırında Tavuk", "Kuru Fasulye", "Izgara Köfte"]
    ok = await plan_kaydet.call({"ogunler": [f"{d.isoformat()}|dinner_main|{name}" for d, name in zip(days, mains)]})
    assert "kaydedildi" in ok, ok

    # Ayni gunde iki yemek: kural ihlali
    bad = await plan_kaydet.call({"uzerine_yaz": True, "ogunler": [
        f"{days[0].isoformat()}|dinner_main|Fırında Tavuk",
        f"{days[0].isoformat()}|dinner_salad|Çoban Salata",
    ]})
    assert "Plan kaydedilmedi" in bad


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
    assert context.index("Ev kuralları") < context.index("## Aktif plan")


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

    assert "Balık kullanma" in reply and "Protein ağırlıklı olsun" in reply
    assert "Eski kural" not in reply
    assert "liste değişmedi" in (
        await run(handlers, "rules_replace", "/kurallari_yaz\nHer öğünde 2 yemek olsun\nHer öğünde 3 yemek olsun")
    )[0]
    assert "Henüz ev kuralı yok" in (await run(handlers, "rules_replace", "/kurallari_yaz sil"))[0]
    assert "Tüm listeyi" in (await run(handlers, "rules_replace", "/kurallari_yaz"))[0]


@pytest.mark.asyncio
async def test_rule_commands_are_admin_only(handlers):
    reply = (await run(handlers, "rule_add", "/kural_ekle Balık kullanma", user_id=999))[0]

    assert "yalnızca admin" in reply
    assert "Henüz ev kuralı yok" in (await run(handlers, "rules", "/kurallar"))[0]
