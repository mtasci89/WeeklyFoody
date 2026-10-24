"""Asistanla her şey: menü onayı, kiler ve görseller (API ve Telegram)."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.tools import MealAgentToolset
from app.db.models import Base, SessionState, WeeklyPlanningSession
from app.planner.service import MealPlannerService
from tests.conftest import seed_recipes


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


class Notifier:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


async def call(toolset, name, **kwargs):
    return await next(t for t in toolset.build() if t.name == name).call(kwargs)


# --- menuyu_onayla ------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_can_approve_and_publish_the_menu(db, settings, session_factory):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session()
    notifier = Notifier()
    toolset = MealAgentToolset(settings, session_factory, notifier=notifier)

    out = await call(toolset, "menuyu_onayla")
    again = await call(toolset, "menuyu_onayla")

    assert "onaylandı ve alıcılara" in out
    assert db.get(WeeklyPlanningSession, session.id).state == SessionState.PUBLISHED
    assert {chat for chat, _ in notifier.sent} == set(settings.all_recipient_ids)
    assert toolset.touched_session_id == session.id
    assert "zaten onaylı" in again


@pytest.mark.asyncio
async def test_approval_without_telegram_only_approves(db, settings, session_factory):
    session = await MealPlannerService(db, settings).create_or_get_weekly_session()

    out = await call(MealAgentToolset(settings, session_factory), "menuyu_onayla")

    assert out.endswith("menüsü onaylandı.")
    assert db.get(WeeklyPlanningSession, session.id).state == SessionState.APPROVED


@pytest.mark.asyncio
async def test_approval_without_a_plan_is_explicit(settings, session_factory):
    assert "Onaylanacak bir menü yok" in await call(MealAgentToolset(settings, session_factory), "menuyu_onayla")


# --- kiler ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pantry_can_be_listed_added_and_removed(settings, session_factory):
    toolset = MealAgentToolset(settings, session_factory)

    assert await call(toolset, "kiler") == "Kiler boş."
    assert await call(toolset, "kiler", islem="ekle", malzemeler=["Tuz", " zeytinyağı ", "tuz"]) == "Kilerde: tuz, zeytinyağı"
    assert await call(toolset, "kiler", islem="cikar", malzemeler=["TUZ"]) == "Kilerde: zeytinyağı"


# --- API: gorsel -------------------------------------------------------------------

TOKEN = "g" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class RecordingAgent:
    def __init__(self):
        self.calls = []

    async def reply(self, chat_id, message, images=None, timeout=None, channel="telegram"):
        self.calls.append((message, images))

        class Reply:
            text, ok, tool_calls, plan_session_id = "3 yemek ekledim.", True, [], None

        return Reply()


@pytest.fixture()
def api(settings):
    from app.api import create_api_app

    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        seed_recipes(db)
    agent = RecordingAgent()
    client = TestClient(create_api_app(settings.model_copy(update={"app_api_token": TOKEN}), Session, agent=agent))
    yield client, agent
    engine.dispose()


def test_chat_accepts_images(api):
    client, agent = api
    png = base64.b64encode(b"\x89PNG-liste").decode()

    body = client.post(
        "/api/v1/sohbet", headers=AUTH,
        json={"mesaj": "bunları veritabanına ekle", "gorseller": [{"mime": "image/png", "veri": png}]},
    ).json()

    assert body["metin"] == "3 yemek ekledim."
    message, images = agent.calls[0]
    assert message == "bunları veritabanına ekle"
    assert [(g.mime, g.data) for g in images] == [("image/png", b"\x89PNG-liste")]


def test_image_only_message_is_allowed_but_empty_is_not(api):
    client, agent = api
    jpg = base64.b64encode(b"jpegdata").decode()

    assert client.post("/api/v1/sohbet", headers=AUTH, json={"gorseller": [{"mime": "image/jpeg", "veri": jpg}]}).status_code == 200
    assert client.post("/api/v1/sohbet", headers=AUTH, json={"mesaj": "  "}).status_code == 422


def test_bad_images_are_rejected(api):
    client, _ = api
    ok = base64.b64encode(b"x" * 10).decode()

    wrong_type = client.post("/api/v1/sohbet", headers=AUTH, json={"gorseller": [{"mime": "application/pdf", "veri": ok}]})
    broken = client.post("/api/v1/sohbet", headers=AUTH, json={"gorseller": [{"mime": "image/png", "veri": "%%%bozuk%%%"}]})
    too_many = client.post("/api/v1/sohbet", headers=AUTH, json={"gorseller": [{"mime": "image/png", "veri": ok}] * 5})

    assert wrong_type.status_code == 422 and "Desteklenmeyen" in wrong_type.json()["detail"]
    assert broken.status_code == 422 and "bozuk" in broken.json()["detail"]
    assert too_many.status_code == 422


# --- Telegram: fotograf ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_photo_goes_to_the_agent_with_its_caption(settings):
    from app.bot.handlers import TelegramHandlers

    class File:
        async def download_as_bytearray(self):
            return bytearray(b"jpeg-bytes")

    class Photo:
        def __init__(self, size):
            self.size = size

        async def get_file(self):
            return File()

    class Message:
        caption = "bunları ekle"
        document = None
        photo = [Photo("kucuk"), Photo("buyuk")]

        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    class Update:
        effective_message = Message()
        effective_user = type("U", (), {"id": settings.admin_telegram_user_id})()
        effective_chat = type("C", (), {"id": 5})()

    class Bot:
        async def send_message(self, *a, **k):
            pass

        async def send_chat_action(self, *a, **k):
            pass

    handlers = TelegramHandlers(settings, Bot())
    handlers.agent = RecordingAgent()
    update = Update()

    await handlers.photo(update, None)

    message, images = handlers.agent.calls[0]
    assert message == "bunları ekle"
    assert [(g.mime, g.data) for g in images] == [("image/jpeg", b"jpeg-bytes")]
    assert update.effective_message.replies == ["3 yemek ekledim."]
