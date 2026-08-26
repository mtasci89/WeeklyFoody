from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


DAY_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

TR_DAY_NAMES = {
    0: "Pazartesi",
    1: "Salı",
    2: "Çarşamba",
    3: "Perşembe",
    4: "Cuma",
    5: "Cumartesi",
    6: "Pazar",
}


def next_week_start(today: date | None = None, timezone: str = "Europe/Istanbul") -> date:
    if today is None:
        today = datetime.now(ZoneInfo(timezone)).date()
    current_monday = today - timedelta(days=today.weekday())
    return current_monday + timedelta(days=7)


def week_dates(week_start: date) -> list[date]:
    return [week_start + timedelta(days=i) for i in range(7)]


def week_end(week_start: date) -> date:
    return week_start + timedelta(days=6)

