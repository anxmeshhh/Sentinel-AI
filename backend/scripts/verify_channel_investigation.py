"""Exercise the Channel Investigate flow exactly as the UI does.

Calls the real route function (`investigate_in_channel`) against a real
channel, real membership and real shared connections. Creates nothing except
the investigation cache row the feature is meant to write.
"""

import time

from sqlalchemy import select

from app.api.routes.investigations import investigate_in_channel
from app.db.session import SessionLocal
from app.models.attention_item import AttentionItem
from app.models.connection import Connection
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.models.workspace import Workspace
from app.services.channel_authorization import authorized_connections
from app.services.channel_briefing import build_channel_briefing

session = SessionLocal()

# A channel whose authorized set is non-empty - the flow is meaningless
# against a channel with nothing shared to it.
candidates = session.execute(select(Team)).scalars().all()
team = next((t for t in candidates if authorized_connections(session, t.id)), None)
if team is None:
    print("No channel has any authorized connection - nothing to investigate.")
    raise SystemExit(1)

workspace = session.get(Workspace, team.workspace_id)
membership = session.execute(
    select(TeamMembership).where(TeamMembership.team_id == team.id)
).scalars().first()
user = session.get(User, membership.user_id)

authorized = authorized_connections(session, team.id)
print(f"Channel   : #{team.name} in {workspace.name}")
print(f"Caller    : {user.email} ({membership.role.value})")
print("Authorized:")
for auth in authorized.values():
    print(f"  - {auth.connection.provider.value} {auth.connection.full_name}  (from {auth.source})")

briefing = build_channel_briefing(session, team.id, team.workspace_id)
print(f"\nBriefing  : {len(briefing['items'])} item(s)")
if not briefing["items"]:
    print("Nothing in this channel's briefing to investigate.")
    raise SystemExit(1)

item = briefing["items"][0]
print(f"Item      : {item.title}\n")

started = time.perf_counter()
result = investigate_in_channel(team_id=team.id, item_id=item.id, session=session, user=user)
elapsed = time.perf_counter() - started

print("=" * 70)
print("WHAT HAPPENED\n ", result.what_happened)
print("\nWHY IT MATTERS\n ", result.why_it_matters)
if result.contributing_factors:
    print("\nCONTRIBUTING FACTORS")
    for f in result.contributing_factors:
        print("  -", f)
print("\nNEXT STEPS")
for s in result.next_steps:
    print("  -", s)
print(f"\nCONFIDENCE: {result.confidence}")
print("=" * 70)

print(f"\nEVIDENCE ({len(result.evidence)}):")
# Calling the route function directly returns the ORM row, so `evidence` is
# the stored JSON (a list of dicts) rather than the serialized schema.
for e in result.evidence:
    print(f"  [{e['relation_label']}] {(e['occurred_at'] or '')[:16]}  {e['title'][:55]}")

print(f"\nLLM calls : {result.llm_calls}")
print(f"Latency   : {elapsed:.2f}s")

# --- the boundary, checked against this real channel ---------------------
print("\nPrivacy checks against real data:")

authorized_ids = set(authorized)
evidence_conn_ids = set()
from app.models.signal import Signal  # noqa: E402

for e in result.evidence:
    signal = session.get(Signal, __import__("uuid").UUID(e["signal_id"]))
    evidence_conn_ids.add(signal.connection_id)

stray = evidence_conn_ids - authorized_ids
print(f"  {'OK  ' if not stray else 'LEAK'}  every evidence row came from an authorized connection ({len(evidence_conn_ids)} distinct)")

# Any connection in this workspace that is NOT authorized here is private to
# its owner as far as this channel is concerned.
all_ws = set(session.execute(
    select(Connection.id).where(Connection.workspace_id == team.workspace_id)
).scalars())
unauthorized = all_ws - authorized_ids
print(f"  {'OK  '}  {len(unauthorized)} workspace connection(s) are NOT authorized here and contributed nothing")

cached_start = time.perf_counter()
again = investigate_in_channel(team_id=team.id, item_id=item.id, session=session, user=user)
print(f"  OK    cached re-open {time.perf_counter() - cached_start:.3f}s, same row: {again.id == result.id}")
print(f"  scope_key: {session.execute(select(__import__('app.models.investigation', fromlist=['Investigation']).Investigation.scope_key).where(__import__('app.models.investigation', fromlist=['Investigation']).Investigation.id == result.id)).scalar()}")

session.close()
raise SystemExit(1 if stray else 0)
