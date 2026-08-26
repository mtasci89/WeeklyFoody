from __future__ import annotations

import logging

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramSecurity:
    def __init__(self, settings: Settings):
        self.settings = settings

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and self.settings.admin_telegram_user_id == user_id

    def is_recipient_chat(self, chat_id: int | None) -> bool:
        return chat_id is not None and chat_id in self.settings.telegram_recipient_chat_ids

    def require_admin(self, user_id: int | None) -> bool:
        ok = self.is_admin(user_id)
        if not ok:
            logger.warning("unauthorized_access user_id=%s", user_id)
        return ok

