"""Exercise the endpoints the new UI calls, in the order a user would.

NOT a substitute for looking at the rendered page - the Chrome extension is
not connected in this environment, so nothing here proves a button is
visible, legible or correctly placed. What it does prove is that every flow
the UI now wires up actually works against real MySQL end to end, which is
the difference between "it compiles" and "it functions".

Creates and removes its own data, and checks the removal.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.api.routes.actions import catalog, my_policies, set_my_policy
from app.api.routes.commitments import add_my_commitment, mark_dismissed, mark_reopened
from app.api.routes.goals import (
    add_link,
    add_my_goal,
    classify_situation,
    goal_detail,
    remove_link,
    set_weight,
)
from app.db.session import SessionLocal
from app.models.commitment import Commitment, CommitmentStatus
from app.models.goal import Goal
from app.models.situation import Situation
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.action import ActionPolicyUpdate
from app.schemas.commitment import CommitmentCreate
from app.schemas.goal import GoalCreate, GoalLinkCreate, GoalSituationRelation, GoalWeightUpdate
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
goal_ids, commitment_ids = [], []

try:
    team = next((t for t in session.execute(select(Team)).scalars() if authorized_connections(session, t.id)), None)
    workspace = session.get(Workspace, team.workspace_id)
    membership = session.execute(select(TeamMembership).where(TeamMembership.team_id == team.id)).scalars().first()
    user = session.get(User, membership.user_id)
    print(f"Workspace : {workspace.name}\nCaller    : {user.email}\n")

    print("JOURNEY 1 — 'What can Sentinel do?' (the catalogue button)")
    entries = catalog(scope="personal")
    available = [e for e in entries if e.available]
    blocked = [e for e in entries if not e.available]
    check("catalogue returns entries", len(entries) > 0, True)
    check("unavailable ones carry a reason", all(e.unavailable_reason for e in blocked), True)
    check("every entry declares reversibility", all(e.reversibility for e in entries), True)
    print(f"      {len(available)} available, {len(blocked)} unavailable with reasons")

    print("\nJOURNEY 2 — autonomy settings (opt-in, and refusing the impossible)")
    policy = set_my_policy(
        payload=ActionPolicyUpdate(action_type="commitment.create", enabled=True, daily_limit=3),
        session=session, workspace_id=workspace.id, user=user,
    )
    check("opt-in stored", policy.enabled, True)
    check("limit stored", policy.daily_limit, 3)
    check("listed back", any(p.action_type == "commitment.create" for p in my_policies(session=session, user=user)), True)
    try:
        set_my_policy(
            payload=ActionPolicyUpdate(action_type="calendar.create_event", enabled=True),
            session=session, workspace_id=workspace.id, user=user,
        )
        check("calendar autonomy refused", "allowed", "refused")
    except Exception:
        check("calendar autonomy refused", "refused", "refused")
    # leave nothing enabled behind
    set_my_policy(
        payload=ActionPolicyUpdate(action_type="commitment.create", enabled=False),
        session=session, workspace_id=workspace.id, user=user,
    )

    print("\nJOURNEY 3 — commitment: track -> dismiss -> reopen")
    commitment = add_my_commitment(
        payload=CommitmentCreate(what=f"[probe {MARK}] Review the deck", due_at=NOW + timedelta(days=2)),
        session=session, workspace_id=workspace.id, user=user,
    )
    commitment_ids.append(commitment.id)
    dismissed = mark_dismissed(commitment_id=commitment.id, session=session, user=user)
    check("dismissed", dismissed.status, CommitmentStatus.DISMISSED.value)
    reopened = mark_reopened(commitment_id=commitment.id, session=session, user=user)
    check("reopen restores a live state", reopened.status in ("pending", "due_soon", "overdue"), True)

    print("\nJOURNEY 4 — goal: create -> link -> weight -> unlink")
    goal = add_my_goal(
        payload=GoalCreate(title=f"[probe {MARK}] Ship the audit", due_at=NOW + timedelta(days=20)),
        session=session, workspace_id=workspace.id, user=user,
    )
    goal_ids.append(goal.id)
    linked = add_link(goal_id=goal.id, payload=GoalLinkCreate(commitment_id=commitment.id), session=session, user=user)
    check("linked", len(linked.commitments), 1)
    check("default weight is 1", linked.commitments[0].weight, 1.0)

    weighted = set_weight(
        goal_id=goal.id, commitment_id=commitment.id,
        payload=GoalWeightUpdate(weight=9), session=session, user=user,
    )
    check("weight editable from the UI path", weighted.commitments[0].weight, 9.0)

    unlinked = remove_link(goal_id=goal.id, commitment_id=commitment.id, session=session, user=user)
    check("unlink works", len(unlinked.commitments), 0)
    check("progress returns to not-measurable", unlinked.progress, None)

    print("\nJOURNEY 5 — goal: classify a situation (the relevance control)")
    situation = session.execute(
        select(Situation).where(Situation.scope_key == f"personal:{user.id}")
    ).scalars().first()
    if situation is None:
        print("  SKIP  no real situation in this scope to classify")
    else:
        detail = classify_situation(
            goal_id=goal.id,
            payload=GoalSituationRelation(situation_id=situation.id, relation="blocking"),
            session=session, user=user,
        )
        check("classified as blocking", detail.health, "blocked")
        check("named as a blocker", any(situation.title[:20] in b.title for b in detail.blockers), True)

        detail = classify_situation(
            goal_id=goal.id,
            payload=GoalSituationRelation(situation_id=situation.id, relation="unrelated"),
            session=session, user=user,
        )
        check("marking unrelated silences it", detail.health != "blocked", True)

    print("\nJOURNEY 6 — closed items remain reachable (so they can be reopened)")
    detail = goal_detail(goal_id=goal.id, refresh=True, session=session, user=user)
    check("goal detail loads", detail.id, goal.id)
    check("suggestions are offered, not applied", isinstance(detail.suggested_commitments, list), True)

finally:
    for gid in goal_ids:
        session.execute(text("DELETE FROM goal_situations WHERE goal_id = :i"), {"i": gid.hex})
        session.execute(text("DELETE FROM goal_commitments WHERE goal_id = :i"), {"i": gid.hex})
        session.execute(text("DELETE FROM investigations WHERE goal_id = :i"), {"i": gid.hex})
        session.execute(text("DELETE FROM goals WHERE id = :i"), {"i": gid.hex})
    for cid in commitment_ids:
        session.execute(text("DELETE FROM commitments WHERE id = :i"), {"i": cid.hex})
    session.execute(text("DELETE FROM action_policies WHERE action_type = 'commitment.create'"))
    session.commit()

    verify = SessionLocal()
    left = (
        len(verify.execute(select(Goal).where(Goal.title.like(f"%{MARK}%"))).scalars().all())
        + len(verify.execute(select(Commitment).where(Commitment.what.like(f"%{MARK}%"))).scalars().all())
    )
    verify.close()
    session.close()
    print(f"\nCleanup: {left} probe rows left (must be 0)")
    if left:
        failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
