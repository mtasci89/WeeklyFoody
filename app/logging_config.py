from __future__ import annotations

import logging
import re
import sys


class SecretFilter(logging.Filter):
    secret_patterns = (
        re.compile(r"/bot[^/\s]+/"),
        re.compile(r"(key=)[^&\s]+", re.IGNORECASE),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        forbidden = (
            "TELEGRAM_BOT_TOKEN",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "telegram_bot_token",
            "openai_api_key",
            "gemini_api_key",
        )
        if any(token in msg for token in forbidden):
            record.msg = "[redacted log message containing a secret-like key]"
            record.args = ()
            return True
        redacted = msg
        for pattern in self.secret_patterns:
            redacted = pattern.sub(lambda match: f"{match.group(1)}[redacted]" if match.lastindex else "/bot[redacted]/", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s event=%(message)s",
        stream=sys.stdout,
    )
    secret_filter = SecretFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(secret_filter)
    for handler in root_logger.handlers:
        handler.addFilter(secret_filter)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
