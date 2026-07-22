"""Second measurement pass: is "a service you depend on is degrading" real?

The first audit killed four hypotheses outright and showed that this
mailbox's threads are one-way service notifications, not conversations. But
the *content* of those notifications was interesting - decommissioning,
pausing, quota exceeded - and two of them were the same project escalating.

This measures that specific shape before any of it is built, including how
much noise the rule lets through, because "action required" is also how
marketing writes subject lines.
"""

import re
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.services.mail_signals import extract_address

NOW = datetime.now(timezone.utc)

# Deliberately narrow, and about *state changes to a resource you have*, not
# about urgency language. "Act now" and "Don't miss out" are marketing;
# "has been paused" is a fact about your account.
JEOPARDY = {
    "shutdown": r"\b(decommission\w*|shutting down|shut down|end[- ]of[- ]life|sunset\w*|discontinu\w*|retire[ds]?)\b",
    "suspended": r"\b(paused|suspend\w*|disabled|deactivat\w*|locked|restricted)\b",
    "expiring": r"\b(expir\w*|renew\w*|due|overdue|lapsed?)\b",
    "over_limit": r"\b(quota|bandwidth|usage|limit|exceed\w*|throttl\w*|over[- ]?age)\b",
    "deletion": r"\b(will be deleted|permanently removed|data loss|purged?)\b",
}

# Words that mean the sender is selling, not warning.
MARKETING = re.compile(
    r"\b(sale|discount|% off|offer|deal|webinar|newsletter|blog|tips|guide|"
    r"upgrade now|try |free trial|invite|join us|register|announcing)\b", re.I
)

session = SessionLocal()

connection = session.execute(
    select(Connection).where(Connection.provider == Provider.GMAIL)
).scalars().first()
owner = (connection.org or "").lower()

signals = session.execute(
    select(Signal).where(Signal.connection_id == connection.id, Signal.type == SignalType.EMAIL)
    .order_by(Signal.occurred_at.asc())
).scalars().all()

print(f"Mailbox: {connection.full_name} - {len(signals)} emails\n")

hits = []
for s in signals:
    payload = s.payload or {}
    subject = payload.get("subject") or ""
    sender = (extract_address(payload.get("from")) or "").lower()
    if sender == owner:
        continue
    kinds = [k for k, pattern in JEOPARDY.items() if re.search(pattern, subject, re.I)]
    if not kinds:
        continue
    marketing = bool(MARKETING.search(subject))
    hits.append((s.occurred_at, sender, subject, kinds, marketing))

print("=" * 78)
print(f"RAW MATCHES: {len(hits)} of {len(signals)} emails ({len(hits)/len(signals)*100:.1f}%)")
print("=" * 78)
for when, sender, subject, kinds, marketing in hits:
    flag = "NOISE?" if marketing else "      "
    print(f"  {flag} {when.date()}  [{','.join(kinds):22}] {sender[:28]:28} {subject[:44]}")

clean = [h for h in hits if not h[4]]
print(f"\nAfter dropping marketing language: {len(clean)}")

# --- the part that makes it a *situation* rather than a match -------------
print()
print("=" * 78)
print("CORRELATION: same sender domain, does anything escalate?")
print("=" * 78)
by_domain = defaultdict(list)
for when, sender, subject, kinds, marketing in clean:
    by_domain[sender.split("@")[-1]].append((when, subject, kinds))

multi = {d: v for d, v in by_domain.items() if len(v) >= 2}
print(f"  domains with 2+ jeopardy messages: {len(multi)}")
for domain, msgs in multi.items():
    print(f"\n  {domain}:")
    for when, subject, kinds in sorted(msgs):
        print(f"    {when.date()}  [{','.join(kinds)}]  {subject[:56]}")

print()
print("=" * 78)
print("SINGLETONS (one message, no progression)")
print("=" * 78)
for domain, msgs in by_domain.items():
    if len(msgs) == 1:
        when, subject, kinds = msgs[0]
        age = (NOW - when.replace(tzinfo=timezone.utc)).days
        print(f"  {age:3}d  {domain[:26]:26} {subject[:48]}")

session.close()
