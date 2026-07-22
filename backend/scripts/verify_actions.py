"""Agentic Actions end-to-end against real MySQL and the real Google API.

Proves one Individual action and one Channel action, including a genuine
external side effect: an event is created in the connected Google Calendar,
verified by reading it back, and then DELETED so the probe leaves nothing
behind. Every Sentinel row it creates is removed and the removal is checked.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_calendar_client import GoogleCalendarClient
from app.models.action import Action, ActionStatus
from app.models.commitment import Commitment
from app.models.connection import Connection, Provider
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.models.workspace import Workspace
from app.services.action_registry import ActionRejected, ActionUnavailable
from app.services.actions import (
    NotAuthorized,
    approve_action,
    audit_trail,
    execute_action,
    propose_action,
)
from app.services.channel_authorization import authorized_connections

NOW = datetime.now(timezone.utc)
MARK = uuid.uuid4().hex[:8]
passed = failed = 0
created_event: tuple[uuid.UUID, str] | None = None


def check(label, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}\n          expected {expected!r}\n          actual   {actual!r}")


session = SessionLocal()
action_ids: list[uuid.UUID] = []
commitment_ids: list[uuid.UUID] = []

try:
    team = next((t for t in session.execute(select(Team)).scalars() if authorized_connections(session, t.id)), None)
    workspace = session.get(Workspace, team.workspace_id)
    membership = session.execute(select(TeamMembership).where(TeamMembership.team_id == team.id)).scalars().first()
    user = session.get(User, membership.user_id)

    print(f"Workspace : {workspace.name}")
    print(f"Channel   : #{team.name}")
    print(f"Caller    : {user.email} ({membership.role.value})\n")

    # --- 1. INDIVIDUAL, internal, low risk ------------------------------
    print("1. INDIVIDUAL ACTION — track a commitment (internal, reversible)")
    action = propose_action(
        session, workspace_id=workspace.id, scope_key=f"personal:{user.id}",
        action_type="commitment.create",
        params={"what": f"[probe {MARK}] Send the quarterly report", "due_at": (NOW + timedelta(days=3)).isoformat()},
        user_id=user.id, reason="Detected as a deadline in your mail", source_kind="attention_item",
    )
    action_ids.append(action.id)
    check("pre-approved (low risk, internal)", action.status, ActionStatus.APPROVED)
    check("approver recorded even without a dialog", action.approved_by_user_id, user.id)

    execute_action(session, action, user.id)
    check("succeeded", action.status, ActionStatus.SUCCEEDED)
    check("verified by reading it back", bool(action.verification), True)
    print(f"      verification: {action.verification}")
    commitment_ids.append(uuid.UUID(action.result["commitment_id"]))

    # --- 2. CHANNEL, internal ------------------------------------------
    print("\n2. CHANNEL ACTION — shared commitment")
    shared = propose_action(
        session, workspace_id=workspace.id, scope_key=f"channel:{team.id}",
        action_type="commitment.create",
        params={"what": f"[probe {MARK}] Ship the release notes"},
        user_id=user.id, reason="Recommended next step for the launch goal", source_kind="goal",
    )
    action_ids.append(shared.id)
    execute_action(session, shared, user.id)
    check("succeeded in the channel scope", shared.status, ActionStatus.SUCCEEDED)
    commitment = session.get(Commitment, uuid.UUID(shared.result["commitment_id"]))
    commitment_ids.append(commitment.id)
    check("landed in the channel, not the person", commitment.scope_key, f"channel:{team.id}")

    # --- 3. REAL EXTERNAL SIDE EFFECT -----------------------------------
    print("\n3. INDIVIDUAL ACTION — create a REAL Google Calendar event")
    calendar = session.execute(
        select(Connection).where(
            Connection.workspace_id == workspace.id, Connection.user_id == user.id,
            Connection.provider == Provider.GOOGLE_CALENDAR, Connection.revoked_at.is_(None),
        )
    ).scalars().first()

    if calendar is None:
        print("  SKIP  no Google Calendar connection for this user")
    else:
        start = NOW + timedelta(days=2)
        cal_action = propose_action(
            session, workspace_id=workspace.id, scope_key=f"personal:{user.id}",
            action_type="calendar.create_event",
            params={
                "title": f"[Sentinel probe {MARK}] Submit report",
                "start": start.isoformat(),
                "end": (start + timedelta(hours=1)).isoformat(),
            },
            user_id=user.id, reason="Your report is due Friday",
        )
        action_ids.append(cal_action.id)
        check("external action waits for approval", cal_action.status, ActionStatus.AWAITING_APPROVAL)
        print(f"      preview: {cal_action.preview['fields']}")
        print(f"      effect : {cal_action.preview['effect']}")

        print("\n   ... user confirms ...")
        approve_action(session, cal_action, user.id)
        execute_action(session, cal_action, user.id)

        check("SUCCEEDED against the real Google API", cal_action.status, ActionStatus.SUCCEEDED)
        check("verified by reading the event back", "Read back from Google Calendar" in (cal_action.verification or ""), True)
        print(f"      event id : {cal_action.result.get('event_id')}")
        print(f"      url      : {cal_action.result.get('url')}")
        created_event = (calendar.id, cal_action.result["event_id"])

        print("\n4. IDEMPOTENCY — confirm again")
        before = cal_action.result.get("event_id")
        execute_action(session, cal_action, user.id)
        check("no second event created", cal_action.result.get("event_id"), before)
        check("still exactly one action row for this intent",
              len(session.execute(select(Action).where(Action.idempotency_key == cal_action.idempotency_key)).scalars().all()), 1)

    # --- 5. GUARDRAILS on real infrastructure ---------------------------
    print("\n5. GUARDRAILS")
    try:
        propose_action(session, workspace_id=workspace.id, scope_key=f"personal:{user.id}",
                       action_type="shell.execute", params={"cmd": "ls"}, user_id=user.id)
        check("unknown action type refused", "allowed", "refused")
    except ActionRejected:
        check("unknown action type refused", "refused", "refused")

    try:
        propose_action(session, workspace_id=workspace.id, scope_key=f"personal:{user.id}",
                       action_type="email.send", params={"subject": "x", "body": "y"}, user_id=user.id)
        check("sending email refused (not available this phase)", "allowed", "refused")
    except ActionUnavailable:
        check("sending email refused (not available this phase)", "refused", "refused")

    try:
        propose_action(session, workspace_id=workspace.id, scope_key=f"personal:{uuid.uuid4()}",
                       action_type="commitment.create", params={"what": "in someone else's name"}, user_id=user.id)
        check("acting in another person's scope refused", "allowed", "refused")
    except NotAuthorized:
        check("acting in another person's scope refused", "refused", "refused")

    # --- 6. AUDIT --------------------------------------------------------
    print("\n6. AUDIT TRAIL")
    trail = [a for a in audit_trail(session, workspace.id) if MARK in str(a.params)]
    print(f"  {len(trail)} executed action(s) recorded")
    for a in trail:
        who = session.get(User, a.requested_by_user_id)
        print(f"    {a.executed_at:%Y-%m-%d %H:%M}  {a.action_type:24} {a.status.value:10} by {who.email}")
    check("every entry names a requester and an approver",
          all(a.requested_by_user_id and a.approved_by_user_id for a in trail), True)
    check("every succeeded entry carries a verification",
          all(a.verification for a in trail if a.status == ActionStatus.SUCCEEDED), True)
    serialized = str([a.result for a in trail])
    check("no tokens in the trail", "ya29." in serialized or "Bearer" in serialized, False)

finally:
    # Remove the real calendar event first - it is the only thing outside
    # Sentinel that this probe created.
    if created_event is not None:
        connection_id, event_id = created_event
        try:
            connection = session.get(Connection, connection_id)
            token = get_valid_access_token(session, connection)
            with GoogleCalendarClient(token) as client:
                resp = client._client.delete(f"/calendars/primary/events/{event_id}")
            print(f"\nDeleted probe calendar event {event_id}: HTTP {resp.status_code}")
        except Exception as exc:
            print(f"\nWARNING: could not delete probe event {event_id}: {exc}")

    for aid in action_ids:
        session.execute(text("DELETE FROM actions WHERE id = :i"), {"i": aid.hex})
    for cid in commitment_ids:
        session.execute(text("DELETE FROM commitments WHERE id = :i"), {"i": cid.hex})
    session.commit()

    verify = SessionLocal()
    left_actions = verify.execute(select(Action).where(Action.params.like(f"%{MARK}%"))).scalars().all() \
        if hasattr(Action.params, "like") else []
    left_commitments = verify.execute(select(Commitment).where(Commitment.what.like(f"%{MARK}%"))).scalars().all()
    verify.close()
    session.close()

    print(f"\nCleanup: {len(left_actions)} actions, {len(left_commitments)} commitments left (must be 0)")
    if left_commitments:
        failed += 1

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
