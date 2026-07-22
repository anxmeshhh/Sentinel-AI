"""Commitment Intelligence end-to-end against the real database.

Calls the real route functions, then deletes exactly what it created and
proves it - route handlers commit internally, so rollback would revert
nothing (the lesson from the Phase 2 and investigation probes).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.api.routes.commitments import (
    add_channel_commitment,
    add_my_commitment,
    channel_commitments,
    mark_dismissed,
    mark_resolved,
    my_commitments,
)
from app.db.session import SessionLocal
from app.models.commitment import Commitment, CommitmentStatus
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.commitment import CommitmentCreate, CommitmentResolve
from app.services.channel_authorization import authorized_connections

NOW = datetime.now(timezone.utc)
MARK = uuid.uuid4().hex[:8]
passed = failed = 0


def check(label, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}\n          expected {expected!r}\n          actual   {actual!r}")


session = SessionLocal()
created: list[uuid.UUID] = []

try:
    team = next(
        (t for t in session.execute(select(Team)).scalars() if authorized_connections(session, t.id)),
        None,
    )
    if team is None:
        print("No channel with authorized connections - cannot exercise the channel layer.")
        raise SystemExit(1)

    workspace = session.get(Workspace, team.workspace_id)
    membership = session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team.id)
    ).scalars().first()
    user = session.get(User, membership.user_id)

    print(f"Workspace : {workspace.name}")
    print(f"Channel   : #{team.name}")
    print(f"Caller    : {user.email}\n")

    print("1. INDIVIDUAL — state a private commitment")
    mine = add_my_commitment(
        payload=CommitmentCreate(what=f"[probe {MARK}] Send the quarterly report", due_at=NOW + timedelta(hours=10)),
        session=session, workspace_id=workspace.id, user=user,
    )
    created.append(mine.id)
    check("created", mine.what.endswith("Send the quarterly report"), True)
    check("due soon (inside 72h horizon)", mine.status, CommitmentStatus.DUE_SOON.value)
    check("recorded as manual", mine.source, "manual")

    print("\n2. INDIVIDUAL — an overdue one")
    overdue = add_my_commitment(
        payload=CommitmentCreate(what=f"[probe {MARK}] Renew the domain", due_at=NOW - timedelta(days=2)),
        session=session, workspace_id=workspace.id, user=user,
    )
    created.append(overdue.id)
    check("overdue", overdue.status, CommitmentStatus.OVERDUE.value)

    mine_list = my_commitments(session=session, workspace_id=workspace.id, user=user)
    probe_rows = [c for c in mine_list if MARK in c.what]
    check("both listed privately", len(probe_rows), 2)
    check("overdue sorts first", MARK in probe_rows[0].what and probe_rows[0].status == "overdue", True)

    print("\n3. CHANNEL — state a shared commitment")
    shared = add_channel_commitment(
        team_id=team.id,
        payload=CommitmentCreate(
            what=f"[probe {MARK}] Ship the revised proposal", due_at=NOW + timedelta(days=4), owner_label="backend team"
        ),
        session=session, user=user,
    )
    created.append(shared.id)
    check("created in the channel", shared.status, CommitmentStatus.PENDING.value)
    check("owner recorded", shared.owner_label, "backend team")

    print("\n4. ISOLATION — the two lists do not bleed into each other")
    channel_list = channel_commitments(team_id=team.id, session=session, user=user)
    personal_list = my_commitments(session=session, workspace_id=workspace.id, user=user)
    channel_probe = [c.what for c in channel_list if MARK in c.what]
    personal_probe = [c.what for c in personal_list if MARK in c.what]
    check("channel sees only the shared one", len(channel_probe), 1)
    check("private ones absent from the channel", any("quarterly report" in w for w in channel_probe), False)
    check("shared one absent from the private list", any("revised proposal" in w for w in personal_probe), False)

    print("\n5. LIFECYCLE — resolve and dismiss are different endings")
    resolved = mark_resolved(
        commitment_id=mine.id, payload=CommitmentResolve(reason="Sent it this morning"), session=session, user=user
    )
    check("resolved", resolved.status, CommitmentStatus.RESOLVED.value)
    check("reason recorded", resolved.resolution_reason, "Sent it this morning")

    dismissed = mark_dismissed(commitment_id=overdue.id, session=session, user=user)
    check("dismissed, not resolved", dismissed.status, CommitmentStatus.DISMISSED.value)

    remaining = [c for c in my_commitments(session=session, workspace_id=workspace.id, user=user) if MARK in c.what]
    check("both leave the live list", len(remaining), 0)

    print("\n6. COST")
    print("  LLM calls: 0 (this module has no synthesis step at all)")

finally:
    for commitment_id in created:
        session.execute(text("DELETE FROM commitments WHERE id = :i"), {"i": commitment_id.hex})
    session.commit()

    verify = SessionLocal()
    leftover = verify.execute(
        select(Commitment).where(Commitment.what.like(f"%{MARK}%"))
    ).scalars().all()
    verify.close()
    session.close()

    print(f"\nCleanup verification: {len(leftover)} probe rows left (must be 0)")
    if leftover:
        failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
