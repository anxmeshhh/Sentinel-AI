"""Week-over-week movement, computed from what is already stored.

Every other surface in Sentinel answers "what is true now". This answers "is
it getting better or worse", which is the one question an executive view has
to answer and the only one a snapshot cannot. It needs no new data: attention
items carry `created_at` and signals carry `occurred_at`, so the history has
been accumulating since the first sync and nothing has ever read it as a
series.

Deterministic throughout - counts over two windows and a subtraction. No LLM,
no new pipeline, no second executive engine: this is a small reader that the
existing status endpoint composes into the card it already returns.

Scope is the caller's own connections, passed in, so a trend can no more span
members than any other read in the system.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.attention_item import AttentionItem, AttentionOrigin
from app.models.signal import Signal

WEEK = timedelta(days=7)


@dataclass(frozen=True)
class Trend:
    """One measure across two consecutive weeks.

    `direction` is derived rather than stored so it cannot disagree with the
    numbers, and `worse` is explicit because it is NOT the same as "up": more
    signals analysed is good, more critical findings is not, and only the
    caller knows which way a given measure points.
    """

    label: str
    current: int
    previous: int

    @property
    def delta(self) -> int:
        return self.current - self.previous

    @property
    def direction(self) -> str:
        if self.delta > 0:
            return "up"
        return "down" if self.delta < 0 else "flat"

    @property
    def percent_change(self) -> float | None:
        """None when there is no baseline - a jump from zero is not a
        percentage, and reporting one as "infinite growth" would be noise."""
        if self.previous == 0:
            return None
        return round((self.delta / self.previous) * 100, 1)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "current": self.current,
            "previous": self.previous,
            "delta": self.delta,
            "direction": self.direction,
            "percent_change": self.percent_change,
        }


def _count_attention(
    session: Session,
    workspace_id: uuid.UUID,
    connection_ids: set[uuid.UUID],
    since: datetime,
    until: datetime,
    *,
    min_priority: float | None = None,
) -> int:
    """Detected items created in a window. Manual reminders are excluded:
    they measure how much the user wrote down, not what Sentinel found."""
    if not connection_ids:
        return 0
    query = select(func.count()).select_from(AttentionItem).where(
        AttentionItem.workspace_id == workspace_id,
        AttentionItem.connection_id.in_(connection_ids),
        AttentionItem.origin == AttentionOrigin.DETECTED,
        AttentionItem.created_at >= since,
        AttentionItem.created_at < until,
    )
    if min_priority is not None:
        query = query.where(AttentionItem.priority >= min_priority)
    return int(session.execute(query).scalar_one())


def _count_signals(
    session: Session,
    workspace_id: uuid.UUID,
    connection_ids: set[uuid.UUID],
    since: datetime,
    until: datetime,
) -> int:
    if not connection_ids:
        return 0
    return int(session.execute(
        select(func.count()).select_from(Signal).where(
            Signal.workspace_id == workspace_id,
            Signal.connection_id.in_(connection_ids),
            Signal.occurred_at >= since,
            Signal.occurred_at < until,
        )
    ).scalar_one())


def weekly_trends(
    session: Session,
    workspace_id: uuid.UUID,
    connection_ids: set[uuid.UUID],
    *,
    now: datetime | None = None,
) -> list[Trend]:
    """This week against the one before it, for the caller's own connections.

    Three measures, chosen because each moves for a different reason:
    volume (how much arrived), findings (how much needed a person) and
    critical (how much was urgent). Read together they separate "a quieter
    week" from "the same week, noticed less".
    """
    now = now or datetime.now(tz=None).astimezone()
    this_start = now - WEEK
    last_start = now - (WEEK * 2)

    return [
        Trend(
            "Signals analysed",
            _count_signals(session, workspace_id, connection_ids, this_start, now),
            _count_signals(session, workspace_id, connection_ids, last_start, this_start),
        ),
        Trend(
            "Findings detected",
            _count_attention(session, workspace_id, connection_ids, this_start, now),
            _count_attention(session, workspace_id, connection_ids, last_start, this_start),
        ),
        Trend(
            "Critical findings",
            _count_attention(session, workspace_id, connection_ids, this_start, now, min_priority=0.8),
            _count_attention(session, workspace_id, connection_ids, last_start, this_start, min_priority=0.8),
        ),
    ]


# A "Resolved this week" measure is deliberately absent. AttentionItem gets
# only `created_at` from TimestampMixin - there is no column recording WHEN a
# row moved to DONE or DISMISSED, so the question "how much got cleared this
# week" cannot be answered from stored data. Counting resolved rows by
# `created_at` would silently report when they were raised instead, which is a
# different fact wearing the right label. Adding the column is a schema change
# and a separate decision; until then this reports three measures it can
# actually stand behind rather than four where one is a guess.


def risk_direction(trends: list[Trend]) -> str:
    """Which way risk moved, in one word.

    Reads the critical trend only. Deliberately not a blended score: an index
    mixing four measures would be a number nobody could check, and this has to
    be traceable to a count the user can see for themselves.
    """
    critical = next((t for t in trends if t.label == "Critical findings"), None)
    if critical is None or critical.delta == 0:
        return "steady"
    return "rising" if critical.delta > 0 else "easing"
