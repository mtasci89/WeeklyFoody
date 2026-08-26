from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import SessionState, WeeklyPlanningSession
from app.formatting import format_meal_plan
from app.shopping.service import ShoppingListService

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        ...


class WeeklyWorkflowService:
    def __init__(self, db: Session, settings: Settings, notifier: Notifier):
        self.db = db
        self.settings = settings
        self.notifier = notifier

    async def publish_final(self, session: WeeklyPlanningSession) -> bool:
        if session.state == SessionState.PUBLISHED or session.published_at is not None:
            return False
        if session.state != SessionState.APPROVED or not session.meal_plan:
            raise ValueError("Cannot publish before approval")
        shopping_items = ShoppingListService(self.db, self.settings).generate(session.meal_plan)
        shopping_text = ShoppingListService(self.db, self.settings).format(shopping_items)
        final_text = f"{format_meal_plan(session, final=True)}\n\n{shopping_text}"
        for chat_id in self.settings.all_recipient_ids:
            try:
                await self.notifier.send_message(chat_id, final_text, parse_mode="Markdown")
            except Exception:
                logger.exception("telegram_send_failed chat_id=%s", chat_id)
                raise
        session.state = SessionState.PUBLISHED
        session.published_at = datetime.utcnow()
        self.db.commit()
        logger.info("final_plan_published week_start=%s session_id=%s recipients=%s", session.week_start, session.id, len(self.settings.all_recipient_ids))
        return True

