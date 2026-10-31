from __future__ import annotations

import asyncio
import sqlite3
from datetime import date

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.config import Settings
from app.db.models import TelegramRecipient, WeeklyPlanningSession
from app.web_panel import create_web_app

SECRETS = {
    "telegram_bot_token": "123:SUPERSECRET_TELEGRAM",
    "openai_api_key": "sk-SUPERSECRET_OPENAI",
    "gemini_api_key": "AIza_SUPERSECRET_GEMINI",
    "anthropic_api_key": "sk-ant-SUPERSECRET_ANTHROPIC",
    "web_panel_token": "SUPERSECRET_PANEL",
}


# --- SEC-01: sirlar jobstore'a yazilmamali ------------------------------


def test_scheduler_jobstore_holds_no_secrets(tmp_path):
    """APScheduler job argumanlarini jobstore tablosuna pickle'liyor.

    Eskiden `settings.model_dump()` argument olarak geciliyordu ve her sir
    veritabani dosyasina duz metin olarak yaziliyordu; dosya docker-compose
    ile mount ediliyor ve README duzenli yedeklenmesini soyluyor.
    """
    from app.scheduler.weekly import build_scheduler

    db_path = tmp_path / "jobs.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path}", admin_telegram_user_id=111, **SECRETS
    )

    async def run() -> None:
        scheduler = build_scheduler(settings)
        scheduler.start()
        await asyncio.sleep(0.2)
        scheduler.shutdown(wait=False)

    asyncio.run(run())

    con = sqlite3.connect(db_path)
    try:
        stored = con.execute("select id, job_state from apscheduler_jobs").fetchall()
    finally:
        con.close()
    assert {row[0] for row in stored} == {"weekly_meal_plan", "weekly_recipe_discovery", "daily_recipe_discovery"}
    blob = b"".join(row[1] for row in stored)
    for name, value in SECRETS.items():
        assert value.encode() not in blob, f"{name} jobstore'a yazilmis"


def test_scheduler_jobs_take_no_arguments():
    """Argumansiz isler, hicbir sirrin pickle'lanamayacagini garanti eder."""
    from app.scheduler.weekly import build_scheduler

    settings = Settings(database_url="sqlite:///:memory:", telegram_bot_token="t", admin_telegram_user_id=1)
    scheduler = build_scheduler(settings)

    for job in scheduler.get_jobs():
        assert job.kwargs == {}, f"{job.id} hala kwargs tasiyor"
        assert job.args == ()


# --- RUN-01: Railway postgres yolu acilmali ----------------------------


def test_scheduler_builds_with_railway_style_postgres_url():
    """`postgresql://` on-eki psycopg2'ye cozulurse acilista patliyordu."""
    from app.scheduler.weekly import build_scheduler

    settings = Settings(
        database_url="postgresql://user:pw@host:5432/railway",
        telegram_bot_token="t",
        admin_telegram_user_id=1,
    )

    scheduler = build_scheduler(settings)

    store = scheduler._jobstores["default"]
    assert store.engine.url.drivername == "postgresql+psycopg"


# --- DB-01: Telegram kimlikleri BIGINT olmali --------------------------


@pytest.mark.parametrize(
    ("table", "column"),
    [(WeeklyPlanningSession.__table__, "admin_chat_id"), (TelegramRecipient.__table__, "chat_id")],
)
def test_telegram_ids_are_bigint_on_postgres(table, column):
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))

    line = next(row.strip() for row in ddl.splitlines() if row.strip().startswith(column))
    assert "BIGINT" in line, f"{table.name}.{column} -> {line}"


@pytest.mark.parametrize("chat_id", [-1001234567890, 7123456789])
def test_supergroup_and_modern_user_ids_round_trip(db, chat_id):
    """INTEGER ile bu degerler PostgreSQL'de NumericValueOutOfRange verirdi."""
    db.add(TelegramRecipient(chat_id=chat_id, label="aile"))
    db.commit()
    stored = WeeklyPlanningSession(
        week_start=date(2026, 8, 31), week_end=date(2026, 9, 6), admin_chat_id=chat_id
    )
    db.add(stored)
    db.commit()

    assert stored.admin_chat_id == chat_id


# --- SEC-02: panel hataya kapali ---------------------------------------


def test_panel_refuses_to_start_without_a_token(tmp_path):
    """Eskiden token bos oldugunda kontrol tamamen atlaniyordu."""
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'p.db'}", web_panel_token="")

    with pytest.raises(ValueError, match="WEB_PANEL_TOKEN"):
        create_web_app(settings)


def test_panel_is_disabled_by_default():
    """Varsayilan yapilandirma artik paneli acmiyor; acan kisi token verir."""
    assert Settings().web_panel_enabled is False


def test_panel_rejects_empty_and_wrong_tokens(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Base

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'p.db'}", web_panel_token="dogru-token")
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    client = TestClient(create_web_app(settings, sessionmaker(bind=engine, future=True)))

    assert client.get("/").status_code == 401
    assert client.get("/?token=").status_code == 401
    assert client.get("/?token=yanlis").status_code == 401
    assert client.get("/api/recipes?token=yanlis").status_code == 401
    assert client.get("/?token=dogru-token").status_code == 200
    assert client.get("/", headers={"x-panel-token": "dogru-token"}).status_code == 200


# --- RUN-02: haftalik is sessizce olmemeli -----------------------------


@pytest.mark.asyncio
async def test_weekly_plan_job_notifies_admin_on_failure(monkeypatch, settings):
    import app.planner.service as planner_service
    import app.scheduler.weekly as weekly

    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id, text, **kwargs):
            sent.append((chat_id, text))

    async def boom(self, week_start=None, regenerate=False):
        raise RuntimeError("LLM 503 Service Unavailable")

    monkeypatch.setattr(planner_service.MealPlannerService, "create_or_get_weekly_session", boom)
    monkeypatch.setattr(weekly, "get_settings", lambda: settings)
    monkeypatch.setattr(weekly, "_CURRENT_BOT", FakeBot())

    # Patlamamali: hata yutulup admin'e bildirilir
    await weekly.weekly_plan_job()

    assert len(sent) == 1
    chat_id, text = sent[0]
    assert chat_id == settings.admin_telegram_user_id
    assert "hata" in text and "/regenerate" in text


@pytest.mark.asyncio
async def test_weekly_plan_job_tolerates_legacy_kwargs(monkeypatch, settings):
    """Eski surumden kalmis kalici job kayitlari kwargs tasiyor olabilir."""
    import app.scheduler.weekly as weekly

    monkeypatch.setattr(weekly, "get_settings", lambda: settings)
    monkeypatch.setattr(weekly, "_CURRENT_BOT", None)

    await weekly.weekly_plan_job(settings_values={"eski": "payload"})


# --- RUN-03: hicbir mesaj cevapsiz kalmamali ---------------------------


@pytest.mark.asyncio
async def test_error_handler_answers_the_user_and_alerts_admin(settings):
    from app.bot.handlers import TelegramHandlers

    replies: list[str] = []
    admin_alerts: list[tuple[int, str]] = []

    class FakeMessage:
        async def reply_text(self, text, **kwargs):
            replies.append(text)

    class FakeBot:
        async def send_message(self, chat_id, text, **kwargs):
            admin_alerts.append((chat_id, text))

    class FakeUpdate:
        effective_message = FakeMessage()
        effective_chat = type("C", (), {"id": 999})()

    class FakeContext:
        error = RuntimeError("beklenmedik")

    handlers = TelegramHandlers(settings, FakeBot())

    await handlers.on_error(FakeUpdate(), FakeContext())

    assert len(replies) == 1
    assert "aksilik" in replies[0]
    assert admin_alerts == [(settings.admin_telegram_user_id, "Bot bir hata aldı: RuntimeError: beklenmedik")]


@pytest.mark.asyncio
async def test_error_handler_survives_a_failing_reply(settings):
    """Hata yakalayicinin kendisi patlarsa dongu kirilir."""
    from app.bot.handlers import TelegramHandlers

    class FakeMessage:
        async def reply_text(self, text, **kwargs):
            raise RuntimeError("telegram down")

    class FakeBot:
        async def send_message(self, chat_id, text, **kwargs):
            raise RuntimeError("telegram down")

    class FakeUpdate:
        effective_message = FakeMessage()
        effective_chat = None

    class FakeContext:
        error = ValueError("ilk hata")

    handlers = TelegramHandlers(settings, FakeBot())

    await handlers.on_error(FakeUpdate(), FakeContext())


@pytest.mark.asyncio
async def test_error_handler_handles_updates_without_a_message(settings):
    from app.bot.handlers import TelegramHandlers

    class FakeBot:
        async def send_message(self, chat_id, text, **kwargs):
            pass

    handlers = TelegramHandlers(settings, FakeBot())

    await handlers.on_error(object(), type("Ctx", (), {"error": RuntimeError("x")})())


def test_error_handler_is_registered():
    from app.bot.telegram import build_application

    settings = Settings(telegram_bot_token="123:abc", admin_telegram_user_id=1)

    application = build_application(settings)

    assert application.error_handlers, "add_error_handler cagrilmamis"


def test_panel_handles_non_ascii_tokens(tmp_path):
    """compare_digest str uzerinde ASCII olmayan karakterde TypeError atar;
    bu da 401 yerine 500 demek olurdu. Sorgu dizesi ASCII olmayan token
    tasiyabilir (HTTP basliklari tasiyamaz), o yuzden yol budur."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Base

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'p.db'}", web_panel_token="şifrem-çğü")
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    client = TestClient(create_web_app(settings, sessionmaker(bind=engine, future=True)))

    assert client.get("/?token=yanlış").status_code == 401
    assert client.get("/?token=şifrem-çğü").status_code == 200
