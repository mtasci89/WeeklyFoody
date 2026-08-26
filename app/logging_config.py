from __future__ import annotations

import logging
import sys


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        forbidden = ("TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY", "telegram_bot_token", "openai_api_key")
        if any(token in msg for token in forbidden):
            record.msg = "[redacted log message containing a secret-like key]"
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s event=%(message)s",
        stream=sys.stdout,
    )
    logging.getLogger().addFilter(SecretFilter())

