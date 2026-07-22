"""Run Proactive Intelligence against the real database and measure it.

Reports precision, LLM cost, duplicate behaviour and lifecycle transitions,
for both intelligence layers.
"""

import time

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.connection import Connection, Provider
from app.models.signal import Signal
from app.models.situation import Situation, SituationStatus
from app.models.team import Team
from app.models.workspace import Workspace
from app.services.channel_authorization import authorized_connections
from app.services.investigation import channel_scope, personal_scope
from app.services.proactive import refresh_situations

session = SessionLocal()


def show(situations, label):
    print(f"\n  {label}: {len(situations)} situation(s)")
    for s in situations:
        print(f"\n    [{s.status.value.upper():9}] importance {s.importance:.2f} · confidence {s.confidence:.2f}"
              f" · {s.evidence_count} evidence · {s.llm_calls} LLM call(s)")
        print(f"      {s.title[:70]}")
        if s.what_is_developing:
            print(f"      WHAT : {s.what_is_developing}")
        if s.why_it_matters:
            print(f"      WHY  : {s.why_it_matters}")
        for step in s.suggested_next_steps:
            print(f"      NEXT : {step}")
        for e in s.evidence:
            print(f"        - {e['occurred_at'][:10]}  [{e['relation']}]  {e['title'][:52]}")


print("=" * 78)
print("LAYER 1 — INDIVIDUAL PROACTIVE INTELLIGENCE (real data)")
print("=" * 78)

connection = session.execute(
    select(Connection).where(Connection.provider == Provider.GMAIL)
).scalars().first()
workspace = session.get(Workspace, connection.workspace_id)
scope = personal_scope(session, workspace.id, connection.user_id)
signal_count = session.execute(
    select(Signal).where(Signal.connection_id.in_(scope.connection_ids))
).scalars().all().__len__()

print(f"  Workspace : {workspace.name}")
print(f"  Scope     : {scope.key} over {len(scope.connection_ids)} connection(s), {signal_count} signals")

started = time.perf_counter()
personal = refresh_situations(session, workspace.id, scope)
first_pass = time.perf_counter() - started
show(personal, "Detected")
print(f"\n  First pass: {first_pass:.2f}s, {sum(s.llm_calls for s in personal)} LLM call(s) total")

print("\n" + "=" * 78)
print("DEDUPLICATION — a second run must not create a second card")
print("=" * 78)
before_ids = {s.id for s in personal}
before_calls = sum(s.llm_calls for s in personal)
started = time.perf_counter()
again = refresh_situations(session, workspace.id, scope)
second_pass = time.perf_counter() - started
after_ids = {s.id for s in again}
after_calls = sum(s.llm_calls for s in again)
print(f"  situations before : {len(before_ids)}")
print(f"  situations after  : {len(after_ids)}")
print(f"  same rows         : {before_ids == after_ids}")
print(f"  extra LLM calls   : {after_calls - before_calls}   (must be 0 - evidence did not change)")
print(f"  second pass       : {second_pass:.2f}s")

# Live rows only. Resolved rows are history and legitimately outnumber the
# live list - counting them here once reported a false duplicate.
live_rows = session.execute(
    select(Situation).where(Situation.scope_key == scope.key, Situation.status != SituationStatus.RESOLVED)
).scalars().all()
print(f"  live rows in db   : {len(live_rows)} (no duplicates: {len(live_rows) == len(after_ids)})")

print("\n" + "=" * 78)
print("LAYER 2 — CHANNEL PROACTIVE INTELLIGENCE (real data)")
print("=" * 78)

teams = session.execute(select(Team)).scalars().all()
team = next((t for t in teams if authorized_connections(session, t.id)), None)
if team is None:
    print("  No channel has authorized connections - nothing to detect.")
else:
    cscope = channel_scope(session, team.id)
    print(f"  Channel   : #{team.name}")
    print(f"  Scope     : {cscope.key} over {len(cscope.connection_ids)} connection(s)")
    channel_situations = refresh_situations(session, team.workspace_id, cscope)
    show(channel_situations, "Detected")

    print("\n" + "=" * 78)
    print("PRIVACY — did any unauthorized connection contribute?")
    print("=" * 78)
    authorized_ids = set(cscope.connection_ids)
    stray = set()
    for s in channel_situations:
        for e in s.evidence:
            sig = session.get(Signal, __import__("uuid").UUID(e["signal_id"]))
            if sig.connection_id not in authorized_ids:
                stray.add(e["title"])
    print(f"  evidence from unauthorized connections: {len(stray)}  {'OK' if not stray else stray}")

    all_ws_conns = set(session.execute(
        select(Connection.id).where(Connection.workspace_id == team.workspace_id)
    ).scalars())
    print(f"  workspace connections not authorized here: {len(all_ws_conns - authorized_ids)}")

    print(f"\n  personal scope key: {scope.key}")
    print(f"  channel scope key : {cscope.key}")
    print(f"  scopes are separate rows: "
          f"{len(session.execute(select(Situation)).scalars().all())} total situation rows across both")

session.close()
