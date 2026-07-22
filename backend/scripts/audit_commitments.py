"""Can Sentinel detect commitments from the data it actually has?

The feasibility question this module lives or dies on: a commitment is a
promise made *in a conversation*, and conversations live in message bodies.
This codebase never stores bodies. So before designing anything, measure what
commitment evidence actually exists in the stored corpus.
"""

import re
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.services.deadline_parser import KEYWORD_RE, find_deadline
from app.services.mail_signals import extract_address

NOW = datetime.now(timezone.utc)

# First-person / assignment promise language - the shape of a commitment.
PROMISE = re.compile(
    r"\b(i'?ll|i will|we'?ll|we will|will send|will share|will fix|will deliver|"
    r"will review|will get back|going to send|planning to|promise[sd]?|"
    r"committed? to|action item|assigned to|owner:|owns |responsible for|"
    r"please (send|review|complete|submit|confirm)|can you (send|review|complete)|"
    r"waiting (on|for)|follow[- ]?up|by end of (day|week)|eod|eow)\b",
    re.I,
)

session = SessionLocal()

print("=" * 74)
print("WHAT SIGNAL TEXT IS AVAILABLE AT ALL")
print("=" * 74)
for signal_type in SignalType:
    rows = session.execute(select(Signal).where(Signal.type == signal_type)).scalars().all()
    if not rows:
        print(f"  {signal_type.value:18} 0 signals")
        continue
    keys = Counter()
    for r in rows[:200]:
        keys.update((r.payload or {}).keys())
    text_fields = [k for k in keys if k in ("subject", "title", "content", "body", "name", "description")]
    print(f"  {signal_type.value:18} {len(rows):4} signals · text fields: {text_fields}")

print()
print("=" * 74)
print("HYPOTHESIS: commitment language in email SUBJECTS")
print("=" * 74)
connection = session.execute(
    select(Connection).where(Connection.provider == Provider.GMAIL)
).scalars().first()
owner = (connection.org or "").lower()
emails = session.execute(
    select(Signal).where(Signal.connection_id == connection.id, Signal.type == SignalType.EMAIL)
).scalars().all()

promise_hits, deadline_hits, both = [], [], []
for s in emails:
    subject = (s.payload or {}).get("subject") or ""
    has_promise = bool(PROMISE.search(subject))
    has_deadline = find_deadline(subject, now=NOW) is not None
    if has_promise:
        promise_hits.append((s, subject))
    if has_deadline:
        deadline_hits.append((s, subject))
    if has_promise and has_deadline:
        both.append((s, subject))

print(f"  emails scanned            : {len(emails)}")
print(f"  promise language in subject: {len(promise_hits)}")
print(f"  parseable deadline         : {len(deadline_hits)}")
print(f"  BOTH (owner + what + when) : {len(both)}")

print("\n  promise-language subjects:")
for s, subject in promise_hits[:15]:
    sender = extract_address((s.payload or {}).get("from")) or "?"
    direction = "SENT BY ME" if sender.lower() == owner else "received  "
    print(f"    [{direction}] {subject[:60]}")

print("\n  deadline subjects:")
for s, subject in deadline_hits[:15]:
    due = find_deadline(subject, now=NOW)
    print(f"    due {due.date() if due else '?'}  {subject[:56]}")

print()
print("=" * 74)
print("CRITICAL: are any emails SENT BY the account owner?")
print("=" * 74)
sent = [s for s in emails if (extract_address((s.payload or {}).get("from")) or "").lower() == owner]
print(f"  emails sent by the owner: {len(sent)} of {len(emails)}")
print("  (a commitment *I* made is one I sent - without sent mail,")
print("   'what did I promise' is not answerable from this corpus)")

print()
print("=" * 74)
print("WHAT ABOUT STRUCTURED SOURCES?")
print("=" * 74)
print(f"  GitHub issues/PRs (assignee + title + state): "
      f"{len(session.execute(select(Signal).where(Signal.type.in_([SignalType.ISSUE, SignalType.PR]))).scalars().all())}")
print(f"  Calendar events (attendees + time)          : "
      f"{len(session.execute(select(Signal).where(Signal.type == SignalType.CALENDAR_EVENT)).scalars().all())}")
docs = session.execute(select(Signal).where(Signal.type == SignalType.DRIVE_FILE)).scalars().all()
print(f"  Drive files with stored content             : {sum(1 for d in docs if (d.payload or {}).get('content'))}")

session.close()
