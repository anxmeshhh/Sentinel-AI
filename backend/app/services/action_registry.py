"""The allow-list of things Sentinel is permitted to do.

This module is the boundary between "the system suggested something" and
"the system may do something". Everything about an action type is declared
here - its risk, which scopes may use it, who must authorize it, the shape of
its parameters, how it executes, and how its outcome is verified.

## Why a registry rather than tools the model can call

A model that can call provider APIs directly decides its own permissions:
whatever it can phrase, it can attempt. Here it can only name a key that
already exists and supply parameters that a Pydantic schema then has to
accept. An action type that is not in this dict cannot be proposed, approved
or executed, no matter what any prompt returns.

Parameters from a model are **untrusted input**, treated exactly like a
request body from the internet: validated server-side, and validated again
against the scope at execution time.

## Read access is not write access

`required_role` is declared per action, not inherited from whether the scope
can *see* the resource. A channel member can read everything the channel is
authorized for; that says nothing about whether they may change shared state,
and several actions here require a channel admin.

## Availability

`available` is a fact about the current deployment, not a wish.
Provider-backed actions are unavailable until their connection exists, and
`unavailable_reason` says which one - so a future Slack or Jira write plugs
in as a new entry rather than a redesign, and nothing here pretends to work
in the meantime.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action import ActionRisk
from app.models.commitment import Commitment
from app.models.connection import Connection, Provider
from app.models.goal import Goal
from app.models.team import ChannelRole

logger = structlog.get_logger("sentinel.actions")


class ActionError(Exception):
    pass


class ActionUnavailable(ActionError):
    pass


class ActionRejected(ActionError):
    """The parameters or the scope are not acceptable. Never retried."""


# --- parameter schemas -----------------------------------------------------


class CreateCommitmentParams(BaseModel):
    what: str = Field(min_length=2, max_length=500)
    due_at: datetime | None = None
    owner_label: str | None = Field(default=None, max_length=200)


class ResolveCommitmentParams(BaseModel):
    commitment_id: uuid.UUID
    reason: str = Field(default="Marked done via Sentinel", max_length=500)


class CreateGoalParams(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    outcome: str | None = Field(default=None, max_length=2000)
    due_at: datetime | None = None


class SnoozeAttentionParams(BaseModel):
    item_id: uuid.UUID
    hours: int = Field(ge=1, le=24 * 30)


class CreateCalendarEventParams(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: datetime
    end: datetime
    # Deliberately absent: attendees. Adding someone to an event notifies
    # them, which makes it an outbound communication to another human - a
    # different risk class that this phase does not execute.


class DraftEmailParams(BaseModel):
    """A draft is written into Sentinel and never sent. Sending is the line
    this phase does not cross: it is irreversible and reaches a third party."""

    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=5000)
    to: str | None = Field(default=None, max_length=300)


@dataclass
class ActionSpec:
    key: str
    label: str
    risk: ActionRisk
    params_model: type[BaseModel]
    # Which scope kinds may run it. Snoozing attention is meaningless for a
    # channel; changing shared goals is meaningless privately.
    scopes: tuple[str, ...] = ("personal", "channel")
    # Minimum channel role. None means any member. Ignored for personal
    # scope, where the actor is the owner by construction.
    required_role: ChannelRole | None = None
    # Does this reach outside Sentinel?
    external: bool = False
    available: bool = True
    unavailable_reason: str | None = None
    # (session, action) -> result dict. Raises on failure.
    execute: Callable[..., dict] = field(default=None, repr=False)
    # (session, action, result) -> (verified: bool, how: str)
    verify: Callable[..., tuple[bool, str]] = field(default=None, repr=False)
    # Human-readable preview built from validated params.
    preview: Callable[..., dict] = field(default=None, repr=False)

    @property
    def needs_approval(self) -> bool:
        """LOW-risk internal actions are reversible Sentinel state - a snooze,
        a reminder - and a second confirmation for them is friction that
        teaches people to click through dialogs. Anything external or shared
        is always previewed and approved."""
        return self.risk is not ActionRisk.LOW or self.external


# --- previews --------------------------------------------------------------


def _preview_commitment(params: CreateCommitmentParams) -> dict:
    return {
        "title": "Track a commitment",
        "fields": {
            "What": params.what,
            "Due": params.due_at.strftime("%d %b %Y") if params.due_at else "no date",
            "Owner": params.owner_label or "unassigned",
        },
        "effect": "Creates a commitment inside Sentinel. Reversible.",
    }


def _preview_resolve(params: ResolveCommitmentParams) -> dict:
    return {
        "title": "Mark a commitment done",
        "fields": {"Reason": params.reason},
        "effect": "Marks it resolved inside Sentinel. Reversible.",
    }


def _preview_goal(params: CreateGoalParams) -> dict:
    return {
        "title": "Set a goal",
        "fields": {
            "Goal": params.title,
            "Outcome": params.outcome or "not stated",
            "Due": params.due_at.strftime("%d %b %Y") if params.due_at else "no date",
        },
        "effect": "Creates a goal inside Sentinel. Reversible.",
    }


def _preview_snooze(params: SnoozeAttentionParams) -> dict:
    return {
        "title": "Snooze this item",
        "fields": {"For": f"{params.hours}h"},
        "effect": "Hides it from your attention list until then. Reversible.",
    }


def _preview_calendar(params: CreateCalendarEventParams) -> dict:
    return {
        "title": "Create a calendar event",
        "fields": {
            "Title": params.title,
            "Start": params.start.strftime("%a %d %b, %H:%M"),
            "End": params.end.strftime("%a %d %b, %H:%M"),
            "Calendar": "Your primary Google Calendar",
        },
        # Says plainly what leaves Sentinel, because this one actually does.
        "effect": "Creates a real event in your Google Calendar. Sentinel sends "
                  "the title and times above, and nothing else.",
    }


def _preview_draft(params: DraftEmailParams) -> dict:
    return {
        "title": "Write a draft",
        "fields": {"To": params.to or "not addressed", "Subject": params.subject},
        "effect": "Saves a draft inside Sentinel. Nothing is sent.",
    }


# --- executors -------------------------------------------------------------


def _execute_create_commitment(session: Session, action) -> dict:
    from app.services.commitments import create_manual_commitment
    from app.services.investigation import Scope

    params = CreateCommitmentParams(**action.params)
    commitment = create_manual_commitment(
        session,
        workspace_id=action.workspace_id,
        scope=Scope(key=action.scope_key),
        what=params.what,
        due_at=params.due_at,
        owner_label=params.owner_label,
        user_id=action.requested_by_user_id,
    )
    return {"commitment_id": str(commitment.id), "what": commitment.what, "status": commitment.status.value}


def _verify_create_commitment(session: Session, action, result: dict) -> tuple[bool, str]:
    stored = session.get(Commitment, uuid.UUID(result["commitment_id"]))
    if stored is None:
        return False, "The commitment was not found after creation"
    if stored.scope_key != action.scope_key:
        return False, "The commitment landed in the wrong scope"
    return True, "Read back from the database in the expected scope"


def _execute_resolve_commitment(session: Session, action) -> dict:
    from app.services.commitments import resolve_commitment

    params = ResolveCommitmentParams(**action.params)
    commitment = session.get(Commitment, params.commitment_id)
    if commitment is None:
        raise ActionRejected("That commitment no longer exists")
    # Re-checked at execution, not just at proposal: the world may have moved
    # between the two, and this is the moment that matters.
    if commitment.scope_key != action.scope_key:
        raise ActionRejected("That commitment belongs to a different context")

    resolve_commitment(session, commitment, reason=params.reason)
    return {"commitment_id": str(commitment.id), "status": commitment.status.value}


def _verify_resolve_commitment(session: Session, action, result: dict) -> tuple[bool, str]:
    from app.models.commitment import CommitmentStatus

    stored = session.get(Commitment, uuid.UUID(result["commitment_id"]))
    if stored is None or stored.status != CommitmentStatus.RESOLVED:
        return False, "The commitment is not resolved"
    return True, "Read back as resolved"


def _execute_create_goal(session: Session, action) -> dict:
    from app.services.goals import create_goal
    from app.services.investigation import Scope

    params = CreateGoalParams(**action.params)
    goal = create_goal(
        session,
        workspace_id=action.workspace_id,
        scope=Scope(key=action.scope_key),
        title=params.title,
        outcome=params.outcome,
        due_at=params.due_at,
        user_id=action.requested_by_user_id,
    )
    return {"goal_id": str(goal.id), "title": goal.title, "health": goal.health.value}


def _verify_create_goal(session: Session, action, result: dict) -> tuple[bool, str]:
    stored = session.get(Goal, uuid.UUID(result["goal_id"]))
    if stored is None or stored.scope_key != action.scope_key:
        return False, "The goal was not found in the expected scope"
    return True, "Read back from the database in the expected scope"


def _execute_snooze_attention(session: Session, action) -> dict:
    from app.models.attention_item import AttentionItem, AttentionState

    params = SnoozeAttentionParams(**action.params)
    item = session.get(AttentionItem, params.item_id)
    if item is None:
        raise ActionRejected("That item no longer exists")

    # An attention item has no scope_key; its owner is the connection's owner.
    # Checked here rather than assumed, so a snooze cannot be aimed at
    # somebody else's item.
    _assert_personal_item(session, action, item)

    item.state = AttentionState.SNOOZED
    item.snoozed_until = datetime.now(timezone.utc) + timedelta(hours=params.hours)
    session.commit()
    return {"item_id": str(item.id), "snoozed_until": item.snoozed_until.isoformat()}


def _assert_personal_item(session: Session, action, item) -> None:
    kind, _, owner_id = action.scope_key.partition(":")
    if kind != "personal":
        raise ActionRejected("Attention items are personal and cannot be acted on by a channel")
    if item.connection_id is None:
        if item.created_by_user_id is None or str(item.created_by_user_id) != owner_id:
            raise ActionRejected("That item does not belong to you")
        return
    connection = session.get(Connection, item.connection_id)
    if connection is None or str(connection.user_id) != owner_id:
        raise ActionRejected("That item does not belong to you")


def _verify_snooze_attention(session: Session, action, result: dict) -> tuple[bool, str]:
    from app.models.attention_item import AttentionItem, AttentionState

    item = session.get(AttentionItem, uuid.UUID(result["item_id"]))
    if item is None or item.state != AttentionState.SNOOZED:
        return False, "The item is not snoozed"
    return True, "Read back as snoozed"


def _execute_create_calendar_event(session: Session, action) -> dict:
    """The one action here with a real external side effect."""
    from app.integrations.google_auth import get_valid_access_token
    from app.integrations.google_calendar_client import GoogleCalendarClient

    params = CreateCalendarEventParams(**action.params)
    if params.end <= params.start:
        raise ActionRejected("The event would end before it starts")

    connection = _google_calendar_connection(session, action)
    if connection is None:
        raise ActionUnavailable("No Google Calendar connection is authorized for this context")

    token = get_valid_access_token(session, connection)
    with GoogleCalendarClient(token) as client:
        event = client.create_event(title=params.title, start=params.start, end=params.end)

    return {
        "event_id": event["id"],
        "title": event.get("title"),
        "url": event.get("url"),
        "start": event.get("start"),
        "connection_id": str(connection.id),
    }


def _google_calendar_connection(session: Session, action) -> Connection | None:
    """The calendar this action may write to, resolved from the action's own
    scope - never from the caller. A channel action writes to a calendar the
    channel is authorized for, and a personal one to the actor's own."""
    kind, _, owner_id = action.scope_key.partition(":")
    if kind == "personal":
        return session.execute(
            select(Connection).where(
                Connection.workspace_id == action.workspace_id,
                Connection.user_id == uuid.UUID(owner_id),
                Connection.provider == Provider.GOOGLE_CALENDAR,
                Connection.revoked_at.is_(None),
            )
        ).scalars().first()

    from app.services.channel_authorization import authorized_connections

    for auth in authorized_connections(session, uuid.UUID(owner_id)).values():
        if auth.connection.provider == Provider.GOOGLE_CALENDAR and auth.connection.revoked_at is None:
            return auth.connection
    return None


def _verify_create_calendar_event(session: Session, action, result: dict) -> tuple[bool, str]:
    """Execution is not completion. The event is read back from Google."""
    from app.integrations.google_auth import get_valid_access_token
    from app.integrations.google_calendar_client import GoogleCalendarClient

    connection = session.get(Connection, uuid.UUID(result["connection_id"]))
    if connection is None:
        return False, "The connection used to create it is gone"

    try:
        token = get_valid_access_token(session, connection)
        with GoogleCalendarClient(token) as client:
            found = client.get_event(result["event_id"])
    except Exception as exc:  # noqa: BLE001 - any failure means "cannot confirm"
        logger.info("calendar_verification_failed", error=str(exc)[:200])
        # UNKNOWN, not FAILED: the event may well exist, and reporting failure
        # would invite the user to create a duplicate.
        return False, "Created, but Sentinel could not read it back to confirm"

    if not found:
        return False, "The provider accepted the request but the event is not there"
    return True, "Read back from Google Calendar after creation"


def _execute_draft(session: Session, action) -> dict:
    """Stored, never sent. Sending is irreversible and reaches a third party,
    which is a line this phase does not cross."""
    params = DraftEmailParams(**action.params)
    return {"subject": params.subject, "to": params.to, "chars": len(params.body), "sent": False}


def _verify_draft(session: Session, action, result: dict) -> tuple[bool, str]:
    return True, "Draft stored in Sentinel; nothing was sent"


# --- the allow-list --------------------------------------------------------

REGISTRY: dict[str, ActionSpec] = {
    spec.key: spec
    for spec in (
        ActionSpec(
            key="commitment.create",
            label="Track a commitment",
            risk=ActionRisk.LOW,
            params_model=CreateCommitmentParams,
            preview=_preview_commitment,
            execute=_execute_create_commitment,
            verify=_verify_create_commitment,
        ),
        ActionSpec(
            key="commitment.resolve",
            label="Mark a commitment done",
            risk=ActionRisk.LOW,
            params_model=ResolveCommitmentParams,
            preview=_preview_resolve,
            execute=_execute_resolve_commitment,
            verify=_verify_resolve_commitment,
        ),
        ActionSpec(
            key="goal.create",
            label="Set a goal",
            risk=ActionRisk.LOW,
            params_model=CreateGoalParams,
            preview=_preview_goal,
            execute=_execute_create_goal,
            verify=_verify_create_goal,
        ),
        ActionSpec(
            key="attention.snooze",
            label="Snooze an attention item",
            risk=ActionRisk.LOW,
            params_model=SnoozeAttentionParams,
            scopes=("personal",),  # attention is personal by construction
            preview=_preview_snooze,
            execute=_execute_snooze_attention,
            verify=_verify_snooze_attention,
        ),
        ActionSpec(
            key="calendar.create_event",
            label="Create a calendar event",
            risk=ActionRisk.MEDIUM,
            params_model=CreateCalendarEventParams,
            external=True,
            # Writing to a calendar the whole channel reads is a shared act,
            # and reading that calendar never implied permission to add to it.
            required_role=ChannelRole.CHANNEL_ADMIN,
            preview=_preview_calendar,
            execute=_execute_create_calendar_event,
            verify=_verify_create_calendar_event,
        ),
        ActionSpec(
            key="email.draft",
            label="Write a draft",
            risk=ActionRisk.LOW,
            params_model=DraftEmailParams,
            preview=_preview_draft,
            execute=_execute_draft,
            verify=_verify_draft,
        ),
        # --- declared, deliberately not available -------------------------
        # These exist so the shape is settled and a future connection plugs
        # in here rather than prompting a redesign. They cannot be proposed.
        ActionSpec(
            key="email.send",
            label="Send an email",
            risk=ActionRisk.HIGH,
            params_model=DraftEmailParams,
            external=True,
            available=False,
            unavailable_reason="Sending mail is not enabled in this phase - Sentinel only drafts.",
        ),
        ActionSpec(
            key="github.create_issue",
            label="Create a GitHub issue",
            risk=ActionRisk.MEDIUM,
            params_model=CreateCommitmentParams,
            external=True,
            required_role=ChannelRole.CHANNEL_ADMIN,
            available=False,
            unavailable_reason="Requires a GitHub OAuth App with write scope (see CONNECTIONS.md).",
        ),
    )
}


def get_spec(action_type: str) -> ActionSpec:
    spec = REGISTRY.get(action_type)
    if spec is None:
        # A type not in the allow-list cannot be proposed at all - this is the
        # line an LLM cannot talk its way past.
        raise ActionRejected(f"Unknown action type: {action_type}")
    return spec


def available_actions(scope_kind: str) -> list[ActionSpec]:
    return [s for s in REGISTRY.values() if s.available and scope_kind in s.scopes]


def validate_params(spec: ActionSpec, raw: dict[str, Any]) -> BaseModel:
    """Every parameter is untrusted, whether it came from a person or a model.

    Pydantic is the only thing that decides what reaches an executor, which
    is why executors can be written against typed fields rather than defensive
    dictionary access.
    """
    try:
        return spec.params_model(**(raw or {}))
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a rejection
        raise ActionRejected(f"Invalid parameters for {spec.key}: {exc}") from exc
