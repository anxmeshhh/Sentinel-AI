"""Every attention lifecycle change is an auditable action.

Done, Snoozed and Dismissed used to be a direct write through
`PATCH /attention/{id}`: no audit row, no verification, no undo. They were
also the most frequent operations in the product, so the things people did
most were the things Sentinel could say least about afterwards.

Snooze already had a registry entry that nothing called. These tests assert
the set is now complete and that the route is a thin adapter over it - the
registry is the only thing that writes the state.

NEW is deliberately excluded: it is not a decision a person makes, it is what
snooze expiry and undo do, so it stays a plain write rather than an audited
claim about work.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.attention import update_state
from app.models.action import Action, ActionStatus
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.attention import AttentionStateUpdate
from app.services.actions import undo_action

NOW = datetime.now(timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def env(session):
    """One workspace, one owner, one bystander - both members, so the only
    thing separating them is whose connection produced the item."""
    ws = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()

    owner = User(email="owner@acme.test", name="Owner")
    bystander = User(email="other@acme.test", name="Other")
    session.add_all([owner, bystander])
    session.flush()
    session.add_all([
        Membership(workspace_id=ws.id, user_id=owner.id, role=Role.EMPLOYEE),
        Membership(workspace_id=ws.id, user_id=bystander.id, role=Role.ORG_ADMIN),
    ])

    conn = Connection(
        workspace_id=ws.id, user_id=owner.id, provider=Provider.GMAIL,
        org="owner@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    session.add(conn)
    session.flush()

    item = AttentionItem(
        workspace_id=ws.id, connection_id=conn.id, type=AttentionType.IMPORTANT_EMAIL,
        origin=AttentionOrigin.DETECTED, state=AttentionState.NEW, source_provider="gmail",
        dedupe_key="email:1", title="Invoice due", why="starred, unread", priority=0.7,
    )
    session.add(item)
    session.commit()
    return {"ws": ws, "owner": owner, "bystander": bystander, "item": item, "_s": session}


def _patch(env, state, **kw):
    return update_state(
        env["item"].id,
        AttentionStateUpdate(state=state, **kw),
        session=env["_s"],
        workspace_id=env["ws"].id,
        user=env["owner"],
    )


# --- the transitions are actions now --------------------------------------


@pytest.mark.parametrize(
    "state,action_type",
    [("done", "attention.done"), ("dismissed", "attention.dismiss")],
)
def test_a_lifecycle_change_is_proposed_executed_and_verified(session, env, state, action_type):
    out = _patch(env, state)
    assert out.state == state

    action = session.query(Action).filter_by(action_type=action_type).one()
    # SUCCEEDED means executed AND confirmed - the verifier re-read the row.
    assert action.status is ActionStatus.SUCCEEDED
    assert action.verification == f"Read back as {state}"
    # The audit trail records who asked and what it was about.
    assert action.requested_by_user_id == env["owner"].id
    assert action.source_kind == "attention_item"
    assert action.source_id == env["item"].id


def test_snooze_still_goes_through_the_registry(session, env):
    """It always had an entry; nothing called it. The route takes a timestamp
    and the action takes a duration, so the conversion is asserted."""
    out = _patch(env, "snoozed", snoozed_until=NOW + timedelta(hours=5))
    assert out.state == "snoozed"

    action = session.query(Action).filter_by(action_type="attention.snooze").one()
    assert action.status is ActionStatus.SUCCEEDED
    assert action.params["hours"] == 5


def test_undo_restores_the_state_the_item_was_actually_in(session, env):
    """Not an assumed NEW: undoing a Done on a snoozed item must not
    resurface it early."""
    env["item"].state = AttentionState.SNOOZED
    session.commit()

    _patch(env, "done")
    action = session.query(Action).filter_by(action_type="attention.done").one()
    assert action.result["previous_state"] == "snoozed"

    undo_action(session, action, env["owner"].id)
    session.refresh(env["item"])
    assert env["item"].state is AttentionState.SNOOZED


def test_returning_an_item_to_new_writes_no_action(session, env):
    """NEW is what expiry and undo do, not a decision worth auditing."""
    _patch(env, "new")
    assert session.query(Action).count() == 0


# --- the registry enforces ownership independently ------------------------


def test_the_registry_refuses_an_item_that_is_not_the_actors(session, env):
    """Belt and braces: the route checks ownership, and so does the executor.

    A caller reaching propose/execute directly - the Assistant's deterministic
    dispatch does exactly that - never passes through the route's check, so
    the action itself has to refuse.
    """
    from app.services.action_registry import ActionRejected
    from app.services.actions import execute_action, propose_action

    action = propose_action(
        session,
        workspace_id=env["ws"].id,
        scope_key=f"personal:{env['bystander'].id}",  # not the owner
        action_type="attention.done",
        params={"item_id": str(env["item"].id)},
        user_id=env["bystander"].id,
    )
    result = execute_action(session, action, env["bystander"].id)

    # Refused inside the executor, recorded as FAILED rather than raising.
    assert result.status is ActionStatus.FAILED
    assert "does not belong to you" in (result.error or "")
    session.refresh(env["item"])
    assert env["item"].state is AttentionState.NEW  # untouched


def test_the_route_still_refuses_a_bystander(session, env):
    """The pre-existing authorization fix stays in force through the adapter."""
    with pytest.raises(HTTPException) as exc:
        update_state(
            env["item"].id,
            AttentionStateUpdate(state="done"),
            session=session,
            workspace_id=env["ws"].id,
            user=env["bystander"],
        )
    assert exc.value.status_code == 404
    assert session.query(Action).count() == 0


def test_a_channel_may_not_act_on_an_attention_item(session, env):
    """Attention is personal by construction - the spec's scopes say so, and
    the executor asserts it rather than trusting the scope key."""
    from app.services.action_registry import ActionRejected
    from app.services.actions import propose_action

    with pytest.raises(ActionRejected):
        propose_action(
            session,
            workspace_id=env["ws"].id,
            scope_key=f"channel:{uuid.uuid4()}",
            action_type="attention.done",
            params={"item_id": str(env["item"].id)},
            user_id=env["owner"].id,
        )
