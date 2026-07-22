"""Run a real investigation against the live database and report on it.

Read-only apart from the investigation row it writes (which is a cache, and
the point of the exercise). Prints evidence, narrative, LLM calls and
latency so the result can be judged rather than assumed.
"""

import time
import uuid
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.attention_item import AttentionItem
from app.models.connection import Connection
from app.models.workspace import Workspace
from app.services.investigation import investigate, personal_scope

session = SessionLocal()

item = session.execute(
    select(AttentionItem)
    .where(AttentionItem.dedupe_key.like("email:%"), AttentionItem.connection_id.isnot(None))
).scalars().first()

if item is None:
    print("No email-derived attention item with a connection - nothing to investigate.")
    raise SystemExit(1)

workspace = session.get(Workspace, item.workspace_id)
connection = session.get(Connection, item.connection_id)
owner_id = connection.user_id

print(f"Workspace : {workspace.name} ({workspace.kind.value})")
print(f"Item      : {item.title}")
print(f"Why       : {item.why}")
print(f"Source    : {connection.full_name}\n")

scope = personal_scope(session, item.workspace_id, owner_id)
print(f"Scope     : {scope.key} over {len(scope.connection_ids)} connection(s)\n")

started = time.perf_counter()
result = investigate(session, item=item, scope=scope, refresh=True)
elapsed = time.perf_counter() - started

print("=" * 70)
print("WHAT HAPPENED")
print(" ", result.what_happened)
print("\nWHY IT MATTERS")
print(" ", result.why_it_matters)
if result.contributing_factors:
    print("\nCONTRIBUTING FACTORS")
    for f in result.contributing_factors:
        print("  -", f)
print("\nRECOMMENDED NEXT STEPS")
for s in result.next_steps:
    print("  -", s)
print(f"\nCONFIDENCE: {result.confidence}")
print("=" * 70)

print(f"\nEVIDENCE ({len(result.evidence)} verified facts, retrieved not generated):")
for e in result.evidence:
    when = (e["occurred_at"] or "")[:16]
    print(f"  [{e['relation_label']}] {when}  {e['title'][:60]}")
    print(f"      {e['actor'] or ''}")

print(f"\nLLM calls : {result.llm_calls}")
print(f"Latency   : {elapsed:.2f}s")

# Cache check: a second call must cost nothing.
started = time.perf_counter()
again = investigate(session, item=item, scope=scope)
cached_elapsed = time.perf_counter() - started
print(f"Cached    : {cached_elapsed:.3f}s, same row: {again.id == result.id}")

session.close()
