"""Sunucu kararlılığı: Telegram'a ulaşılamaması uygulama API'sini düşürmez.

Kullanıcı uygulamada art arda "sunucuya bağlanamadı" aldı. Eskiden Telegram'ın
başlatılması hata verirse tüm süreç kapanıyor, servis yeniden başlarken API de
gidiyordu; artık Telegram arka planda yeniden denenir.
"""
from __future__ import annotations

import pytest

from app.main import _app_api_server, start_telegram


class FakeUpdater:
    running = False

    async def start_polling(self):
        self.running = True


class FlakyApplication:
    """İlk iki denemede ağ hatası veren Telegram uygulaması."""

    def __init__(self, failures=2):
        self.failures = failures
        self.running = False
        self.updater = FakeUpdater()
        self.bot = None
        self.attempts = 0

    async def initialize(self):
        self.attempts += 1
        if self.failures:
            self.failures -= 1
            raise OSError("Telegram'a ulaşılamadı")

    async def start(self):
        self.running = True


@pytest.mark.asyncio
async def test_telegram_start_retries_instead_of_crashing(settings, monkeypatch):
    import app.main as main

    async def no_notice(*_):
        return None

    monkeypatch.setattr(main, "_announce_update", no_notice)
    app = FlakyApplication(failures=2)

    assert await start_telegram(app, settings, first_delay=0, max_delay=0) is True
    assert app.attempts == 3 and app.running and app.updater.running


def test_api_server_keeps_connections_longer_than_the_app(settings, tmp_path):
    from app.api_tls import ensure_certificate

    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    ensure_certificate(cert, key, "127.0.0.1")
    enabled = settings.model_copy(update={
        "app_api_enabled": True, "app_api_token": "t" * 40, "app_api_cert": cert, "app_api_key": key,
    })
    server = _app_api_server(enabled, bot=None)
    assert server.config.timeout_keep_alive > 30  # uygulama boşta bağlantıyı 30 sn'de bırakır
