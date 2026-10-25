from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Protocol
from weakref import WeakValueDictionary

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import SessionState, WeeklyPlanningSession
from app.formatting import format_meal_plan
from app.shopping.service import ShoppingListService

logger = logging.getLogger(__name__)
_publish_locks: WeakValueDictionary = WeakValueDictionary()


def session_lock(session_id: str):
    return _publish_locks.setdefault(session_id, asyncio.Lock())


class Notifier(Protocol):
    async def send_message(self, chat_id: int, text: str, **kwargs) -> None: ...


class WeeklyWorkflowService:
    def __init__(self, db: Session, settings: Settings, notifier: Notifier):
        self.db, self.settings, self.notifier = db, settings, notifier

    async def publish_final(self, session: WeeklyPlanningSession) -> bool:
        lock = session_lock(session.id)
        async with lock:
            self.db.refresh(session)
            if session.state == SessionState.PUBLISHED:
                return False
            if session.state != SessionState.APPROVED or not session.meal_plan:
                raise ValueError("Göndermek için önce güncel menüyü onayla.")
            shopping = ShoppingListService(self.db, self.settings)
            final_text = f"{format_meal_plan(session, final=True)}\n\n{shopping.format(shopping.generate(session.meal_plan))}"
            context = dict(session.context or {})
            version = str(session.draft_version)
            deliveries = dict(context.get("deliveries", {}))
            sent = list(deliveries.get(version, []))
            for chat_id in dict.fromkeys(self.settings.all_recipient_ids):
                if chat_id in sent:
                    continue
                # Persist each successful delivery so a later recipient's failure can be retried.
                from app.bot.messages import split_message
                parts = split_message(final_text)
                progress = dict(context.get("delivery_parts", {}))
                progress_key = f"{version}:{chat_id}"
                for index, part in enumerate(parts):
                    if index < progress.get(progress_key, 0):
                        continue
                    await self.notifier.send_message(chat_id, part)
                    progress[progress_key] = index + 1
                    context["delivery_parts"] = dict(progress)
                    session.context = dict(context)
                    self.db.commit()
                sent.append(chat_id)
                deliveries[version] = list(sent)
                context["deliveries"] = dict(deliveries)
                session.context = dict(context)
                self.db.commit()
            session.state = SessionState.PUBLISHED
            session.published_at = datetime.utcnow()
            context["published_version"] = session.draft_version
            session.context = dict(context)
            self.db.commit()
            logger.info("final_plan_published session_id=%s version=%s", session.id, version)
            return True
