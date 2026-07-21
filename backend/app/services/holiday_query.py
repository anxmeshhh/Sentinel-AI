"""Indian holidays/festivals - sourced live from Google's own public
"Holidays in India" calendar, never hardcoded dates, so lunar-calendar
festivals (Diwali, Eid, Holi, etc.) are always correct for whatever year is
actually queried - Google maintains the dates, we never store or duplicate
them locally (queried fresh every time, consistent with "don't duplicate
what the provider already serves"). Only the category label (National/
Regional/Festival/Observance) and, for regional entries, which state(s)
they're primarily observed in, come from a maintained keyword table below -
that's static text classification of well-known holiday *names*, not dates,
which is a different thing from hardcoding a calendar.
"""

from datetime import datetime

import httpx
import structlog
from sqlalchemy.orm import Session

from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_calendar_client import GoogleCalendarClient
from app.models.connection import Provider
from app.repositories.connections import ConnectionRepository

logger = structlog.get_logger("sentinel.holidays")

INDIAN_HOLIDAY_CALENDAR_ID = "en.indian#holiday@group.v.calendar.google.com"

CATEGORIES = {"national", "regional", "festival", "observance"}

NATIONAL_HOLIDAYS = {"republic day", "independence day", "gandhi jayanti"}

# name fragment (lowercase) -> primarily-observed-in states
REGIONAL_HOLIDAYS: dict[str, list[str]] = {
    "onam": ["Kerala"],
    "pongal": ["Tamil Nadu"],
    "makar sankranti": ["Gujarat", "Maharashtra", "West Bengal", "Punjab"],
    "durga puja": ["West Bengal"],
    "ganesh chaturthi": ["Maharashtra"],
    "baisakhi": ["Punjab"],
    "vaisakhi": ["Punjab"],
    "bihu": ["Assam"],
    "ugadi": ["Karnataka", "Andhra Pradesh", "Telangana"],
    "gudi padwa": ["Maharashtra"],
    "chhath puja": ["Bihar"],
    "chhat puja": ["Bihar"],
    "rath yatra": ["Odisha"],
    "karva chauth": ["Punjab", "Haryana", "Uttar Pradesh"],
    "vishu": ["Kerala"],
    "poila boishakh": ["West Bengal"],
}

# real titles observed from Google's own calendar - includes regional/
# colloquial names (Ramzan Id, Bakrid) alongside the formal ones (Eid
# al-Fitr, Eid al-Adha), since the calendar isn't consistent about which it uses
FESTIVAL_KEYWORDS = {
    "diwali", "deepavali", "holi", "eid", "ramzan id", "bakrid", "christmas",
    "dussehra", "navratri", "navaratri", "janmashtami", "raksha bandhan",
    "guru nanak jayanti", "buddha purnima", "mahavir jayanti", "ram navami",
    "rama navami", "good friday", "muharram", "milad", "shivratri",
    "shivaratri", "guru purnima", "vasant panchami", "holika dahan",
    "holika dahana",
}


def classify_holiday(title: str) -> tuple[str, list[str] | None]:
    lower = title.lower()
    if any(name in lower for name in NATIONAL_HOLIDAYS):
        return "national", None
    for name, states in REGIONAL_HOLIDAYS.items():
        if name in lower:
            return "regional", states
    if any(name in lower for name in FESTIVAL_KEYWORDS):
        return "festival", None
    return "observance", None  # unmatched, lesser-known entries - shown, not hidden


def list_indian_holidays(
    session: Session, workspace_id, *, since: datetime, until: datetime, state: str | None = None
) -> list[dict]:
    """Rides on the same Google Calendar connection/token as the user's own
    calendar - no separate connection needed, holidays aren't a distinct
    "service" the user connects, just a different calendar_id on the same API.
    """
    connection = ConnectionRepository(session, workspace_id).get_for_user(user_id, Provider.GOOGLE_CALENDAR) if user_id else None
    if connection is None:
        return []

    access_token = get_valid_access_token(session, connection)
    try:
        with GoogleCalendarClient(access_token) as client:
            raw_events = client.fetch_events(since, until=until, calendar_id=INDIAN_HOLIDAY_CALENDAR_ID)
    except httpx.HTTPStatusError as exc:
        # Most likely an older connection that hasn't picked up the
        # calendar.readonly scope yet (needs "Reconnect Google") - degrade
        # to an empty list rather than a 500, same as every other
        # not-yet-authorized case in this codebase.
        logger.warning("holiday_fetch_failed", status=exc.response.status_code)
        return []

    holidays = []
    for e in raw_events:
        title = e["payload"]["title"]
        category, states = classify_holiday(title)
        if category == "regional" and state and states and state not in states:
            continue
        holidays.append(
            {
                "title": title,
                "date": e["payload"]["start"],
                "category": category,
                "states": states,
            }
        )
    return holidays
