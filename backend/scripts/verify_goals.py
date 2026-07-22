"""Goal-Based AI end-to-end against the real database.

Runs the brief's own scenario - a channel goal blocked by an overdue backend
commitment - plus an individual goal, through the real route functions.
Cleans up explicitly and proves it: these routes commit internally, so
rollback would revert nothing.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.api.routes.commitments import add_channel_commitment, add_my_commitment
from app.api.routes.goals import (
    add_channel_goal,
    add_my_goal,
    add_link,
    goal_detail,
    mark_achieved,
    my_goals,
)
from app.db.session import SessionLocal
from app.models.commitment import Commitment
from app.models.goal import Goal
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.commitment import CommitmentCreate
from app.schemas.goal import GoalCreate, GoalLinkCreate
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
goal_ids: list[uuid.UUID] = []
commitment_ids: list[uuid.UUID] = []

try:
    team = next((t for t in session.execute(select(Team)).scalars() if authorized_connections(session, t.id)), None)
    if team is None:
        print("No channel with authorized connections.")
        raise SystemExit(1)

    workspace = session.get(Workspace, team.workspace_id)
    membership = session.execute(select(TeamMembership).where(TeamMembership.team_id == team.id)).scalars().first()
    user = session.get(User, membership.user_id)

    print(f"Workspace : {workspace.name}")
    print(f"Channel   : #{team.name}")
    print(f"Caller    : {user.email}\n")

    # --- the brief's scenario, on real infrastructure --------------------
    print("1. CHANNEL GOAL — 'Launch Product V2'")
    goal = add_channel_goal(
        team_id=team.id,
        payload=GoalCreate(
            title=f"[probe {MARK}] Launch Product V2",
            outcome="V2 live for all customers",
            due_at=NOW + timedelta(days=10),
        ),
        session=session, user=user,
    )
    goal_ids.append(goal.id)
    check("created", goal.health, "unknown")
    check("progress is NOT a confident zero", goal.progress, None)
    check("says why", "cannot be determined" in " ".join(goal.health_reasons), True)

    print("\n2. Link a healthy commitment")
    backend = add_channel_commitment(
        team_id=team.id,
        payload=CommitmentCreate(what=f"[probe {MARK}] Finish the backend", due_at=NOW + timedelta(days=5)),
        session=session, user=user,
    )
    commitment_ids.append(backend.id)
    detail = add_link(
        goal_id=goal.id, payload=GoalLinkCreate(commitment_id=backend.id), session=session, user=user
    )
    # ON TRACK - and this is the stabilization pass working. There IS a live
    # situation in this channel (the real Supabase project pause), and until
    # the relevance layer existed it made every goal here at_risk purely for
    # sharing a scope. It shares no signals with this goal's commitments, so
    # it is now correctly UNRELATED and contributes nothing.
    check("on track - no false risk from an unrelated situation", detail.health, "on_track")
    check("no situation noise in the reasons",
          any("situation" in r for r in detail.health_reasons), False)
    check("progress measurable now", detail.progress, 0.0)
    print(f"      reasons: {detail.health_reasons}")

    print("\n3. The backend commitment goes overdue")
    session.execute(
        text("UPDATE commitments SET due_at = :d, status = 'OVERDUE' WHERE id = :i"),
        {"d": NOW - timedelta(days=1), "i": backend.id.hex},
    )
    session.commit()
    detail = goal_detail(goal_id=goal.id, refresh=True, session=session, user=user)

    check("goal is BLOCKED", detail.health, "blocked")
    check("the blocker is named", detail.blockers[0].title, f"[probe {MARK}] Finish the backend")
    check("reason states it", any("overdue" in r for r in detail.health_reasons), True)
    print(f"      reasons: {detail.health_reasons}")

    print("\n4. A second commitment resolves — progress moves on evidence")
    second = add_channel_commitment(
        team_id=team.id,
        payload=CommitmentCreate(what=f"[probe {MARK}] Ship the docs", due_at=NOW + timedelta(days=5)),
        session=session, user=user,
    )
    commitment_ids.append(second.id)
    add_link(goal_id=goal.id, payload=GoalLinkCreate(commitment_id=second.id), session=session, user=user)
    session.execute(
        text("UPDATE commitments SET status = 'RESOLVED', resolved_at = :n WHERE id = :i"),
        {"n": NOW, "i": second.id.hex},
    )
    session.commit()
    detail = goal_detail(goal_id=goal.id, refresh=True, session=session, user=user)
    check("progress is a real ratio", detail.progress, 0.5)
    check("still blocked by the overdue one", detail.health, "blocked")

    # --- individual layer ------------------------------------------------
    print("\n5. INDIVIDUAL GOAL — private, and separate")
    mine = add_my_goal(
        payload=GoalCreate(title=f"[probe {MARK}] Prepare for my interview", due_at=NOW + timedelta(days=3)),
        session=session, workspace_id=workspace.id, user=user,
    )
    goal_ids.append(mine.id)
    private_commitment = add_my_commitment(
        payload=CommitmentCreate(what=f"[probe {MARK}] Review my notes", due_at=NOW + timedelta(days=1)),
        session=session, workspace_id=workspace.id, user=user,
    )
    commitment_ids.append(private_commitment.id)
    detail_mine = add_link(
        goal_id=mine.id, payload=GoalLinkCreate(commitment_id=private_commitment.id), session=session, user=user
    )
    check("private goal assessed independently", detail_mine.health, "at_risk")  # deadline within 72h
    print(f"      reasons: {detail_mine.health_reasons}")

    print("\n6. ISOLATION")
    personal_list = [g.title for g in my_goals(session=session, workspace_id=workspace.id, user=user)]
    check("channel goal absent from the private list",
          any("Launch Product V2" in t for t in personal_list), False)
    check("private goal present for its owner",
          any("Prepare for my interview" in t for t in personal_list), True)

    print("\n7. Cross-scope linking is refused")
    try:
        add_link(goal_id=goal.id, payload=GoalLinkCreate(commitment_id=private_commitment.id),
                 session=session, user=user)
        check("private commitment refused on a channel goal", "allowed", "refused")
    except Exception as exc:
        check("private commitment refused on a channel goal",
              "different context" in str(exc) or "403" in str(exc), True)

    print("\n8. Only a person closes a goal")
    closed = mark_achieved(goal_id=mine.id, session=session, user=user)
    check("achieved", closed.health, "achieved")

    print("\n9. COST")
    total_calls = sum(
        g.llm_calls for g in session.execute(select(Goal).where(Goal.id.in_(goal_ids))).scalars()
    )
    print(f"  LLM calls across the whole scenario: {total_calls}")
    print("  (health itself is arithmetic; the model is only asked to explain a changed state)")

finally:
    for gid in goal_ids:
        session.execute(text("DELETE FROM goal_commitments WHERE goal_id = :i"), {"i": gid.hex})
        session.execute(text("DELETE FROM investigations WHERE goal_id = :i"), {"i": gid.hex})
        session.execute(text("DELETE FROM goals WHERE id = :i"), {"i": gid.hex})
    for cid in commitment_ids:
        session.execute(text("DELETE FROM commitments WHERE id = :i"), {"i": cid.hex})
    session.commit()

    verify = SessionLocal()
    leftover_goals = verify.execute(select(Goal).where(Goal.title.like(f"%{MARK}%"))).scalars().all()
    leftover_commitments = verify.execute(select(Commitment).where(Commitment.what.like(f"%{MARK}%"))).scalars().all()
    verify.close()
    session.close()

    print(f"\nCleanup: {len(leftover_goals)} goals, {len(leftover_commitments)} commitments left (must be 0)")
    if leftover_goals or leftover_commitments:
        failed += 1

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
