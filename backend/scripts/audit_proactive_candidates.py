"""What proactive situations can Sentinel actually detect from today's data?

Measurement before design. Every hypothesis below is checked against the
real database, and the ones that produce nothing get deleted rather than
built on the assumption that data will show up later.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.attention_item import AttentionItem, AttentionState
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.services.mail_signals import extract_address, noise_reason, sender_counts

NOW = datetime.now(timezone.utc)
session = SessionLocal()

print(f"NOW = {NOW.isoformat()}\n")

print("=" * 72)
print("WHAT DATA EXISTS")
print("=" * 72)
for provider in Provider:
    conns = session.execute(select(Connection).where(Connection.provider == provider)).scalars().all()
    total = 0
    for c in conns:
        total += session.execute(
            select(Signal).where(Signal.connection_id == c.id)
        ).scalars().all().__len__()
    print(f"  {provider.value:18} {len(conns)} connection(s), {total} signal(s)")

print()
print("=" * 72)
print("HYPOTHESIS 1: upcoming meeting with unresolved prep")
print("=" * 72)
events = session.execute(
    select(Signal).where(Signal.type == SignalType.CALENDAR_EVENT)
).scalars().all()
upcoming = []
for e in events:
    raw = (e.payload or {}).get("start")
    if not raw:
        continue
    try:
        start = datetime.fromisoformat(raw)
    except ValueError:
        continue
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start > NOW:
        upcoming.append((start, e))
print(f"  calendar events total : {len(events)}")
print(f"  in the future         : {len(upcoming)}")
for start, e in upcoming[:5]:
    print(f"    - {start.isoformat()}  {(e.payload or {}).get('title')}")
print("  VERDICT:", "detectable" if upcoming else "NOT detectable today (no future meetings in the data)")

print()
print("=" * 72)
print("HYPOTHESIS 2: a thread is waiting on you")
print("=" * 72)
print("  A real correspondent wrote to you, you never replied, and it has aged.")
for connection in session.execute(select(Connection).where(Connection.provider == Provider.GMAIL)).scalars():
    owner = (connection.org or "").lower()
    signals = session.execute(
        select(Signal).where(Signal.connection_id == connection.id, Signal.type == SignalType.EMAIL)
        .order_by(Signal.occurred_at.asc())
    ).scalars().all()
    if not signals:
        continue
    counts = sender_counts([s.payload or {} for s in signals])

    threads: dict[str, list[Signal]] = defaultdict(list)
    for s in signals:
        threads[(s.payload or {}).get("thread_id") or s.external_id].append(s)

    waiting = []
    for thread_id, msgs in threads.items():
        last = msgs[-1]
        payload = last.payload or {}
        sender = (extract_address(payload.get("from")) or "").lower()
        if sender == owner:
            continue  # you spoke last
        if noise_reason(payload, counts) is not None:
            continue  # bulk/automated - not a correspondent
        age_days = (NOW - last.occurred_at.replace(tzinfo=timezone.utc)).days
        if age_days < 3:
            continue
        # Did the owner ever participate in this thread? A thread you were
        # never part of is a broadcast, not a conversation awaiting you.
        owner_spoke = any((extract_address((m.payload or {}).get("from")) or "").lower() == owner for m in msgs)
        waiting.append((age_days, sender, payload.get("subject"), len(msgs), owner_spoke))

    waiting.sort(reverse=True)
    print(f"\n  connection {connection.full_name} ({len(signals)} emails, {len(threads)} threads)")
    print(f"    candidate 'awaiting you' threads: {len(waiting)}")
    for age, sender, subject, n, owner_spoke in waiting[:10]:
        mark = "REPLY-EXPECTED" if owner_spoke else "one-way"
        print(f"      {age:3}d  [{mark:14}] {sender[:32]:32} | {(subject or '')[:40]}")

print()
print("=" * 72)
print("HYPOTHESIS 3: deadline approaching with no follow-up")
print("=" * 72)
deadlines = session.execute(
    select(AttentionItem).where(AttentionItem.dedupe_key.like("deadline:%"))
).scalars().all()
print(f"  deadline attention items: {len(deadlines)}")
for d in deadlines[:5]:
    print(f"    - due {d.due_at} | {d.title[:50]}")
print("  VERDICT:", "detectable" if deadlines else "NOT detectable today (no deadline items exist)")

print()
print("=" * 72)
print("HYPOTHESIS 4: aging unresolved attention")
print("=" * 72)
stale = session.execute(
    select(AttentionItem).where(AttentionItem.state == AttentionState.NEW)
).scalars().all()
old = [i for i in stale if (NOW - i.created_at.replace(tzinfo=timezone.utc)).days >= 3]
print(f"  NEW attention items     : {len(stale)}")
print(f"  untouched for 3+ days   : {len(old)}")
for i in old[:5]:
    age = (NOW - i.created_at.replace(tzinfo=timezone.utc)).days
    print(f"    - {age}d  {i.title[:55]}")
print("  VERDICT:", "detectable" if old else "NOT detectable today")

print()
print("=" * 72)
print("HYPOTHESIS 5: escalating correspondent (repeated, unanswered)")
print("=" * 72)
for connection in session.execute(select(Connection).where(Connection.provider == Provider.GMAIL)).scalars():
    owner = (connection.org or "").lower()
    signals = session.execute(
        select(Signal).where(Signal.connection_id == connection.id, Signal.type == SignalType.EMAIL)
    ).scalars().all()
    if not signals:
        continue
    counts = sender_counts([s.payload or {} for s in signals])
    recent = [s for s in signals if (NOW - s.occurred_at.replace(tzinfo=timezone.utc)).days <= 14]
    by_sender = defaultdict(list)
    for s in recent:
        payload = s.payload or {}
        if noise_reason(payload, counts) is not None:
            continue
        addr = (extract_address(payload.get("from")) or "").lower()
        if addr and addr != owner:
            by_sender[addr].append(s)
    repeated = {k: v for k, v in by_sender.items() if len(v) >= 3}
    print(f"  {connection.full_name}: {len(repeated)} non-bulk sender(s) with 3+ messages in 14d")
    for addr, msgs in list(repeated.items())[:5]:
        print(f"    - {addr[:40]:40} {len(msgs)} messages")
    break  # one connection is enough to judge

session.close()
