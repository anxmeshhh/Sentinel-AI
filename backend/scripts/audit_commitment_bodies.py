"""Do the message BODIES contain commitments? Measured before building.

The previous audit ruled out extraction from subjects (0 promise statements
in 190). Ephemeral body processing is a genuinely different input, so it
deserves its own measurement rather than the same answer by assumption.

Bodies are fetched live and never written anywhere. This uses no LLM: the
question is whether promise language exists at all, and a regex answers that
without spending a token or trusting a model's opinion of its own usefulness.
"""

import re
from collections import Counter

from sqlalchemy import select

from app.db.session import SessionLocal
from app.integrations.gmail_client import GmailClient
from app.integrations.google_auth import get_valid_access_token
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.services.mail_signals import extract_address

SAMPLE = 40

# First-person promises, assignments, and requests with an implied owner.
PROMISE = re.compile(
    r"\b(i'?ll\s+\w+|i will\s+\w+|we'?ll\s+\w+|we will\s+\w+|"
    r"i'?m going to\s+\w+|we're going to\s+\w+|"
    r"will (send|share|fix|deliver|review|prepare|update|complete|finish|get back|follow up)|"
    r"(can|could) you (please )?(send|share|review|complete|confirm|update)|"
    r"please (send|share|review|complete|confirm|submit)|"
    r"action item|assigned to|owner:|deliverable|"
    r"by (monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|eod|eow|end of (day|week)))\b",
    re.I,
)

session = SessionLocal()
connection = session.execute(
    select(Connection).where(Connection.provider == Provider.GMAIL)
).scalars().first()
owner = (connection.org or "").lower()

signals = session.execute(
    select(Signal)
    .where(Signal.connection_id == connection.id, Signal.type == SignalType.EMAIL)
    .order_by(Signal.occurred_at.desc())
    .limit(SAMPLE)
).scalars().all()

print(f"Mailbox : {connection.full_name}")
print(f"Sample  : {len(signals)} most recent emails (bodies fetched live, never stored)\n")

token = get_valid_access_token(session, connection)
hits, fetched, failed = [], 0, 0
senders = Counter()

with GmailClient(token) as client:
    for signal in signals:
        try:
            body = client.fetch_message_body(signal.external_id)
        except Exception:
            failed += 1
            continue
        if not body:
            continue
        fetched += 1
        text = " ".join(str(body).split())
        matches = PROMISE.findall(text)
        if matches:
            payload = signal.payload or {}
            sender = extract_address(payload.get("from")) or "?"
            senders[sender] += 1
            hits.append((payload.get("subject") or "", sender, matches[:3], text))

print(f"bodies fetched      : {fetched}")
print(f"fetch failures      : {failed}")
print(f"bodies with promise language: {len(hits)}  ({len(hits)/max(1,fetched)*100:.0f}%)")

print("\n--- matches ---")
for subject, sender, matches, text in hits[:12]:
    direction = "SENT BY ME" if sender.lower() == owner else "received"
    print(f"\n  [{direction}] {sender[:34]}")
    print(f"    subject : {subject[:62]}")
    print(f"    matched : {[' '.join(m) if isinstance(m, tuple) else m for m in matches]}")
    # A little context around the first match, to judge whether it is a real
    # promise or marketing copy wearing promise clothes.
    m = PROMISE.search(text)
    if m:
        start = max(0, m.start() - 70)
        print(f"    context : ...{text[start:m.end() + 90]}...")

print("\n--- who makes these statements ---")
for sender, count in senders.most_common(10):
    print(f"  {count:3}  {sender}")

print("\nNOTE: nothing fetched here was written to the database.")
session.close()
