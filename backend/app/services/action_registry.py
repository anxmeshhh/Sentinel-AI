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

import enum
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action import ActionRisk
from app.models.commitment import Commitment
from app.models.connection import Connection, Provider
from app.models.goal import Goal
from app.models.team import ChannelRole

logger = structlog.get_logger("sentinel.actions")


class Reversibility(str, enum.Enum):
    """What Sentinel can honestly promise about undoing an action.

    Declared per action rather than assumed, because the difference matters
    to a user deciding whether to approve: "you can undo this" and "this is
    permanent" are different offers. Nothing here claims rollback the
    provider cannot actually deliver.
    """

    # Sentinel's own state. Undo restores it exactly.
    REVERSIBLE = "reversible"
    # External, but the provider offers an inverse operation - a created
    # calendar event can be deleted. Not a true rollback: anyone who already
    # saw the change saw it.
    COMPENSATABLE = "compensatable"
    # Cannot be taken back. A sent email is the canonical case, which is why
    # this phase does not send any.
    IRREVERSIBLE = "irreversible"


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


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CreateCalendarEventParams(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: datetime
    end: datetime
    # Adding an attendee makes Google send that person an invitation, so this
    # field turns a private calendar write into an outbound message to a
    # third party. It is supported, capped, validated, and it escalates the
    # action's risk to HIGH - see `risk_for` - so it can never be executed
    # without an explicit preview naming every recipient.
    attendee_emails: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("attendee_emails")
    @classmethod
    def _validate_attendees(cls, value: list[str]) -> list[str]:
        cleaned = []
        for raw in value:
            address = (raw or "").strip().lower()
            if not _EMAIL_RE.match(address):
                raise ValueError(f"Not a valid email address: {raw!r}")
            if address not in cleaned:
                cleaned.append(address)
        return cleaned


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

    # What Sentinel can honestly promise about undoing this.
    reversibility: Reversibility = Reversibility.REVERSIBLE
    # (session, action) -> str describing what was undone. Present only where
    # an inverse genuinely exists; absence is what makes IRREVERSIBLE real
    # rather than a label.
    compensate: Callable[..., str] = field(default=None, repr=False)

    # Some actions change risk with their parameters: a calendar event for
    # yourself is a private write, the same event with attendees is an
    # invitation sent to other people. Declared as a function so the escalation
    # cannot be forgotten at a call site.
    risk_for: Callable[..., ActionRisk] = field(default=None, repr=False)

    # May this ever run without a human present? Default no. See
    # services/action_policy.py - even a true here requires an explicit,
    # per-scope opt-in before anything runs unattended.
    autonomy_eligible: bool = False

    def effective_risk(self, params: BaseModel | None = None) -> ActionRisk:
        if self.risk_for is not None and params is not None:
            return self.risk_for(params)
        return self.risk

    def needs_approval_for(self, risk: ActionRisk) -> bool:
        """LOW-risk internal actions are reversible Sentinel state - a snooze,
        a reminder - and a second confirmation for them is friction that
        teaches people to click through dialogs. Anything external, shared, or
        escalated by its own parameters is always previewed and approved."""
        return risk is not ActionRisk.LOW or self.external

    @property
    def needs_approval(self) -> bool:
        return self.needs_approval_for(self.risk)


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


def _risk_for_calendar(params: CreateCalendarEventParams) -> ActionRisk:
    """An event for yourself is a private write. The same event with
    attendees sends each of them an invitation, which is an outbound message
    to another human - a different thing, and priced as one."""
    return ActionRisk.HIGH if params.attendee_emails else ActionRisk.MEDIUM


def _preview_calendar(params: CreateCalendarEventParams) -> dict:
    fields = {
        "Title": params.title,
        "Start": params.start.strftime("%a %d %b, %H:%M"),
        "End": params.end.strftime("%a %d %b, %H:%M"),
        "Calendar": "Your primary Google Calendar",
    }
    if params.attendee_emails:
        # Every recipient is named. Nobody is invited by a count.
        fields["Invites"] = ", ".join(params.attendee_emails)
        effect = (
            f"Creates a real event in your Google Calendar AND sends an invitation to "
            f"{len(params.attendee_emails)} " + ("person" if len(params.attendee_emails) == 1 else "people") +
            ". They will see the title and times above. Deleting the event later notifies them again."
        )
    else:
        effect = ("Creates a real event in your Google Calendar. Nobody is invited, and Sentinel sends "
                  "the title and times above and nothing else.")
    return {"title": "Create a calendar event", "fields": fields, "effect": effect}


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
        event = client.create_event(
            title=params.title, start=params.start, end=params.end,
            attendee_emails=params.attendee_emails or None,
        )

    return {
        "event_id": event["id"],
        "title": event.get("title"),
        "url": event.get("url"),
        "start": event.get("start"),
        "attendee_emails": params.attendee_emails,
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


# --- compensation ----------------------------------------------------------
#
# Undo, where an inverse genuinely exists. An action with no function here is
# IRREVERSIBLE and says so, rather than offering a button that cannot work.


def _compensate_create_commitment(session: Session, action) -> str:
    from app.services.commitments import dismiss_commitment

    commitment = session.get(Commitment, uuid.UUID(action.result["commitment_id"]))
    if commitment is None:
        return "It was already gone"
    dismiss_commitment(session, commitment, reason="Undone by the person who created it")
    return "The commitment was dismissed"


def _compensate_resolve_commitment(session: Session, action) -> str:
    from app.services.commitments import reopen_commitment

    commitment = session.get(Commitment, uuid.UUID(action.result["commitment_id"]))
    if commitment is None:
        return "It was already gone"
    reopen_commitment(session, commitment)
    return "The commitment was reopened"


def _compensate_create_goal(session: Session, action) -> str:
    from app.services.goals import close_goal

    goal = session.get(Goal, uuid.UUID(action.result["goal_id"]))
    if goal is None:
        return "It was already gone"
    close_goal(session, goal, achieved=False)
    return "The goal was abandoned"


def _compensate_snooze(session: Session, action) -> str:
    from app.models.attention_item import AttentionItem, AttentionState

    item = session.get(AttentionItem, uuid.UUID(action.result["item_id"]))
    if item is None:
        return "It was already gone"
    item.state = AttentionState.NEW
    item.snoozed_until = None
    session.commit()
    return "The item is back in your attention list"


def _compensate_calendar_event(session: Session, action) -> str:
    """Compensation, not rollback.

    The event is deleted, but anyone who was invited already received the
    invitation and will now receive a cancellation. The world does not return
    to how it was, and the message returned here says so rather than
    reporting a clean undo.
    """
    from app.integrations.google_auth import get_valid_access_token
    from app.integrations.google_calendar_client import GoogleCalendarClient

    connection = session.get(Connection, uuid.UUID(action.result["connection_id"]))
    if connection is None:
        raise ActionRejected("The connection used to create it is gone")

    token = get_valid_access_token(session, connection)
    with GoogleCalendarClient(token) as client:
        deleted = client.delete_event(action.result["event_id"])

    if not deleted:
        raise ActionRejected("Google did not confirm the deletion")
    if action.result.get("attendee_emails"):
        return ("The event was deleted. Everyone invited has been notified of the cancellation - "
                "the invitation itself cannot be unsent.")
    return "The event was deleted from your calendar"


def _compensate_draft(session: Session, action) -> str:
    return "The draft was discarded"




# --- Outlook Mail writes ----------------------------------------------------
#
# Real writes to the real mailbox, reached ONLY from here. Every one is
# `external=True`, which by needs_approval_for() means every one is previewed
# and confirmed before it runs - no Microsoft write is ever silent.
#
# All four are genuinely undoable, and the compensations say how: read state and
# flags have exact inverses, and a draft can be deleted. Nothing here sends
# mail: `email.send` remains unavailable for the reason recorded on that entry -
# a sent message has no inverse, so an approval could never be undone.


class MarkMailReadParams(BaseModel):
    message_id: str = Field(min_length=1, max_length=500)
    is_read: bool = True
    # Carried for the preview and audit trail so the record reads like something
    # a human did, not an opaque id.
    subject: str = Field(default="", max_length=300)


class FlagMailParams(BaseModel):
    message_id: str = Field(min_length=1, max_length=500)
    flagged: bool = True
    subject: str = Field(default="", max_length=300)


class OutlookDraftParams(BaseModel):
    to: list[str] = Field(min_length=1, max_length=25)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("to")
    @classmethod
    def _valid_addresses(cls, values: list[str]) -> list[str]:
        for address in values:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address.strip()):
                raise ValueError(f"not a valid email address: {address}")
        return [a.strip() for a in values]


class OutlookReplyParams(BaseModel):
    message_id: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    subject: str = Field(default="", max_length=300)


def _outlook_connection(session: Session, action) -> Connection | None:
    """The mailbox this action may write to, resolved from the action's own
    scope - never from the caller, exactly like the calendar resolver."""
    kind, _, owner_id = action.scope_key.partition(":")
    if kind == "personal":
        return session.execute(
            select(Connection).where(
                Connection.workspace_id == action.workspace_id,
                Connection.user_id == uuid.UUID(owner_id),
                Connection.provider == Provider.MICROSOFT_OUTLOOK_MAIL,
                Connection.revoked_at.is_(None),
            )
        ).scalars().first()

    from app.services.channel_authorization import authorized_connections

    for auth in authorized_connections(session, uuid.UUID(owner_id)).values():
        if auth.connection.provider == Provider.MICROSOFT_OUTLOOK_MAIL and auth.connection.revoked_at is None:
            return auth.connection
    return None


def _outlook_client(session: Session, action):
    from app.integrations.graph_client import GraphClient
    from app.integrations.microsoft_auth import get_valid_access_token

    connection = _outlook_connection(session, action)
    if connection is None:
        raise ActionUnavailable("No Outlook mailbox is authorized for this context")
    return GraphClient(get_valid_access_token(session, connection))


def _preview_mark_read(params: MarkMailReadParams) -> dict:
    verb = "Mark as read" if params.is_read else "Mark as unread"
    return {"summary": f"{verb}: {params.subject or params.message_id[:24]}", "reversible": True}


def _execute_mark_read(session: Session, action) -> dict:
    params = MarkMailReadParams(**action.params)
    with _outlook_client(session, action) as client:
        return client.set_message_read(params.message_id, params.is_read)


def _verify_mark_read(session: Session, action, result: dict) -> tuple[bool, str]:
    """Read the message back from Microsoft - the write is confirmed by the
    provider's own state, not by our request having returned 200."""
    try:
        with _outlook_client(session, action) as client:
            current = client.message(result["message_id"])
    except Exception:  # noqa: BLE001 - a failed read-back is "cannot confirm"
        return False, "Applied, but Sentinel could not read it back to confirm"
    return (current["is_read"] == result["is_read"],
            f"Outlook reports is_read={current['is_read']}")


def _compensate_mark_read(session: Session, action) -> str:
    params = MarkMailReadParams(**action.params)
    with _outlook_client(session, action) as client:
        client.set_message_read(params.message_id, not params.is_read)
    return f"Restored read state to {not params.is_read}"


def _preview_flag(params: FlagMailParams) -> dict:
    verb = "Flag" if params.flagged else "Clear the flag on"
    return {"summary": f"{verb}: {params.subject or params.message_id[:24]}", "reversible": True}


def _execute_flag(session: Session, action) -> dict:
    params = FlagMailParams(**action.params)
    with _outlook_client(session, action) as client:
        return client.set_message_flag(params.message_id, params.flagged)


def _verify_flag(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _outlook_client(session, action) as client:
            current = client.message(result["message_id"])
    except Exception:  # noqa: BLE001
        return False, "Applied, but Sentinel could not read it back to confirm"
    return current["flagged"] == result["flagged"], f"Outlook reports flagged={current['flagged']}"


def _compensate_flag(session: Session, action) -> str:
    params = FlagMailParams(**action.params)
    with _outlook_client(session, action) as client:
        client.set_message_flag(params.message_id, not params.flagged)
    return f"Restored flag to {not params.flagged}"


def _preview_outlook_draft(params: OutlookDraftParams) -> dict:
    return {
        "summary": f"Create a draft to {', '.join(params.to)}: {params.subject}",
        "to": params.to, "subject": params.subject, "chars": len(params.body),
        "sends": False, "reversible": True,
    }


def _execute_outlook_draft(session: Session, action) -> dict:
    """Creates a REAL draft in Outlook - the user will see it there. Nothing is
    sent; sending stays a separate, deliberately unavailable action."""
    params = OutlookDraftParams(**action.params)
    with _outlook_client(session, action) as client:
        return client.create_draft(subject=params.subject, to=params.to, body=params.body)


def _verify_outlook_draft(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _outlook_client(session, action) as client:
            client.message(result["draft_id"])
    except Exception:  # noqa: BLE001
        return False, "Created, but Sentinel could not read it back to confirm"
    return True, "Draft exists in Outlook and was not sent"


def _compensate_outlook_draft(session: Session, action) -> str:
    result = action.result or {}
    draft_id = result.get("draft_id")
    if not draft_id:
        raise ActionRejected("No draft id was recorded, so it cannot be removed")
    with _outlook_client(session, action) as client:
        client.delete_message(draft_id)
    return "Draft moved to Deleted Items in Outlook"


def _preview_outlook_reply(params: OutlookReplyParams) -> dict:
    return {
        "summary": f"Draft a reply to: {params.subject or params.message_id[:24]}",
        "chars": len(params.body), "sends": False, "reversible": True,
    }


def _execute_outlook_reply(session: Session, action) -> dict:
    params = OutlookReplyParams(**action.params)
    with _outlook_client(session, action) as client:
        return client.create_reply_draft(params.message_id, params.body)



# --- Outlook: actually sending -------------------------------------------
#
# The one Microsoft write with no inverse. Everything about it is deliberate:
# HIGH risk, external, IRREVERSIBLE, and NO compensate function - because this
# module's own rule is that an action with no compensation IS irreversible and
# says so, rather than offering an undo button that cannot work. A recipient
# cannot un-see a message.
#
# It is only ever reached by a person clicking send and confirming the preview
# below, which names the recipients, the subject and the message itself. It is
# not autonomy-eligible and is never proposed by the Decision Engine.


def _preview_outlook_send(params: OutlookDraftParams) -> dict:
    """What the user is shown BEFORE the irreversible step. Stored verbatim on
    the action, so the audit record proves what they agreed to send."""
    body = params.body.strip()
    return {
        "summary": f"Send to {', '.join(params.to)}: {params.subject}",
        "to": params.to,
        "subject": params.subject,
        "message": body if len(body) <= 2000 else body[:2000] + "…",
        "chars": len(params.body),
        "sends": True,
        "irreversible": True,
        "warning": "This sends a real email immediately. It cannot be recalled or undone.",
    }


def _execute_outlook_send(session: Session, action) -> dict:
    """Create the draft, then send it - so the audit trail records a real
    message id even though the send itself returns nothing."""
    params = OutlookDraftParams(**action.params)
    sent_after = datetime.now(timezone.utc) - timedelta(seconds=5)
    with _outlook_client(session, action) as client:
        draft = client.create_draft(subject=params.subject, to=params.to, body=params.body)
        client.send_draft(draft["draft_id"])
    return {
        "draft_id": draft["draft_id"],
        "to": params.to,
        "subject": params.subject,
        "sent": True,
        "sent_after": sent_after.isoformat(),
    }


def _verify_outlook_send(session: Session, action, result: dict) -> tuple[bool, str]:
    """Confirmed by finding it in Sent Items - Microsoft's own record that the
    message left the mailbox. A send that cannot be found is reported as
    unverified, never as a success."""
    since = datetime.fromisoformat(result["sent_after"])
    try:
        with _outlook_client(session, action) as client:
            matches = client.find_sent(result["subject"], since)
    except Exception:  # noqa: BLE001 - a failed read-back is "cannot confirm"
        return False, "Sent, but Sentinel could not read Sent Items to confirm"
    if not matches:
        return False, "Sent, but no matching message was found in Sent Items yet"
    return True, f"Found in Sent Items at {matches[0]['sent_at']:%H:%M} - delivery is Microsoft's to complete"


_OUTLOOK_ACTIONS = (
    ActionSpec(
        key="outlook.mark_read",
        label="Mark mail read or unread",
        risk=ActionRisk.LOW,
        params_model=MarkMailReadParams,
        external=True,  # -> always previewed and confirmed
        preview=_preview_mark_read,
        execute=_execute_mark_read,
        verify=_verify_mark_read,
        reversibility=Reversibility.REVERSIBLE,
        compensate=_compensate_mark_read,
    ),
    ActionSpec(
        key="outlook.flag",
        label="Flag or unflag mail",
        risk=ActionRisk.LOW,
        params_model=FlagMailParams,
        external=True,
        preview=_preview_flag,
        execute=_execute_flag,
        verify=_verify_flag,
        reversibility=Reversibility.REVERSIBLE,
        compensate=_compensate_flag,
    ),
    ActionSpec(
        key="outlook.draft",
        label="Write a draft in Outlook",
        risk=ActionRisk.LOW,
        params_model=OutlookDraftParams,
        external=True,
        preview=_preview_outlook_draft,
        execute=_execute_outlook_draft,
        verify=_verify_outlook_draft,
        # Reversible in the strict sense: the draft can be removed and nothing
        # left the mailbox, because nothing was sent.
        reversibility=Reversibility.REVERSIBLE,
        compensate=_compensate_outlook_draft,
    ),
    ActionSpec(
        key="outlook.send",
        label="Send an email",
        risk=ActionRisk.HIGH,
        params_model=OutlookDraftParams,
        external=True,
        preview=_preview_outlook_send,
        execute=_execute_outlook_send,
        verify=_verify_outlook_send,
        # No compensate, on purpose. A sent message has no inverse, and this
        # module treats the ABSENCE of a compensation as what makes
        # IRREVERSIBLE real rather than a label.
        reversibility=Reversibility.IRREVERSIBLE,
        # Never unattended. A person sees the recipients, subject and body and
        # confirms, every single time.
        autonomy_eligible=False,
    ),
    ActionSpec(
        key="outlook.reply_draft",
        label="Draft a reply in Outlook",
        risk=ActionRisk.LOW,
        params_model=OutlookReplyParams,
        external=True,
        preview=_preview_outlook_reply,
        execute=_execute_outlook_reply,
        verify=_verify_outlook_draft,
        reversibility=Reversibility.REVERSIBLE,
        compensate=_compensate_outlook_draft,
    ),
)




# --- Outlook Calendar writes -----------------------------------------------
#
# Reuses CreateCalendarEventParams and _risk_for_calendar from the Google
# calendar action: the rule that attendees escalate a private write into an
# outbound message to other people is the same rule whoever hosts the calendar.
#
# The three writes differ in exactly one honest way - what can be taken back:
#   create  COMPENSATABLE   the event can be deleted
#   update  COMPENSATABLE   the previous values are recorded, so they can be put back
#   cancel  IRREVERSIBLE    attendees were notified, and that cannot be unsent


class UpdateCalendarEventParams(BaseModel):
    event_id: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=300)
    start: datetime | None = None
    end: datetime | None = None
    attendee_emails: list[str] | None = Field(default=None, max_length=20)

    @field_validator("attendee_emails")
    @classmethod
    def _validate_attendees(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for raw in value:
            address = (raw or "").strip().lower()
            if not _EMAIL_RE.match(address):
                raise ValueError(f"Not a valid email address: {raw!r}")
            if address not in cleaned:
                cleaned.append(address)
        return cleaned


class CancelCalendarEventParams(BaseModel):
    event_id: str = Field(min_length=1, max_length=500)
    title: str = Field(default="", max_length=300)
    comment: str = Field(default="", max_length=1000)
    # Carried so the preview can name who will be told, and the audit record
    # shows it. Never used to decide anything - Microsoft notifies, not us.
    attendee_count: int = 0


def _outlook_calendar_connection(session: Session, action) -> Connection | None:
    kind, _, owner_id = action.scope_key.partition(":")
    if kind == "personal":
        return session.execute(
            select(Connection).where(
                Connection.workspace_id == action.workspace_id,
                Connection.user_id == uuid.UUID(owner_id),
                Connection.provider == Provider.MICROSOFT_OUTLOOK_CALENDAR,
                Connection.revoked_at.is_(None),
            )
        ).scalars().first()

    from app.services.channel_authorization import authorized_connections

    for auth in authorized_connections(session, uuid.UUID(owner_id)).values():
        if auth.connection.provider == Provider.MICROSOFT_OUTLOOK_CALENDAR and auth.connection.revoked_at is None:
            return auth.connection
    return None


def _outlook_calendar_client(session: Session, action):
    from app.integrations.graph_client import GraphClient
    from app.integrations.microsoft_auth import get_valid_access_token

    connection = _outlook_calendar_connection(session, action)
    if connection is None:
        raise ActionUnavailable("No Outlook Calendar is authorized for this context")
    return GraphClient(get_valid_access_token(session, connection))


def _risk_for_update(params: UpdateCalendarEventParams) -> ActionRisk:
    """Changing a meeting that has attendees sends every one of them an update.
    Same reasoning as creating with attendees."""
    return ActionRisk.HIGH if params.attendee_emails else ActionRisk.MEDIUM


def _preview_outlook_event(params: CreateCalendarEventParams) -> dict:
    return {
        "summary": f"Create “{params.title}” on {params.start:%a %d %b at %H:%M}",
        "title": params.title,
        "when": f"{params.start:%a %d %b %H:%M} – {params.end:%H:%M}",
        "attendees": params.attendee_emails,
        "notifies": bool(params.attendee_emails),
        "warning": (
            f"{len(params.attendee_emails)} attendee(s) will be sent an invitation."
            if params.attendee_emails else None
        ),
    }


def _execute_outlook_create_event(session: Session, action) -> dict:
    params = CreateCalendarEventParams(**action.params)
    if params.end <= params.start:
        raise ActionRejected("The event would end before it starts")
    with _outlook_calendar_client(session, action) as client:
        event = client.create_event(
            title=params.title, start=params.start, end=params.end,
            attendee_emails=params.attendee_emails or None,
            # An event with attendees gets a Teams link where the tenant
            # supports it; a solo event does not need one.
            online=bool(params.attendee_emails),
        )
    return {"event_id": event["id"], "title": event["title"], "url": event["url"], "join_url": event["join_url"]}


def _verify_outlook_event(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _outlook_calendar_client(session, action) as client:
            event = client.get_event(result["event_id"])
    except Exception:  # noqa: BLE001
        return False, "Applied, but Sentinel could not read it back to confirm"
    if event.get("cancelled"):
        return False, "The event exists but is cancelled"
    return True, f"Outlook has “{event['title']}” at {event['start']:%a %d %b %H:%M}"


def _compensate_outlook_create_event(session: Session, action) -> str:
    result = action.result or {}
    event_id = result.get("event_id")
    if not event_id:
        raise ActionRejected("No event id was recorded, so it cannot be removed")
    with _outlook_calendar_client(session, action) as client:
        client.delete_event(event_id)
    return "Event deleted from Outlook"


def _preview_outlook_update(params: UpdateCalendarEventParams) -> dict:
    changes = []
    if params.title is not None:
        changes.append(f"title → “{params.title}”")
    if params.start is not None:
        changes.append(f"start → {params.start:%a %d %b %H:%M}")
    if params.end is not None:
        changes.append(f"end → {params.end:%H:%M}")
    if params.attendee_emails is not None:
        changes.append(f"attendees → {', '.join(params.attendee_emails) or 'none'}")
    return {
        "summary": "Update the event: " + ("; ".join(changes) or "no changes"),
        "changes": changes,
        "notifies": bool(params.attendee_emails),
        "warning": "Attendees will be notified of the change." if params.attendee_emails else None,
    }


def _execute_outlook_update_event(session: Session, action) -> dict:
    """Records the PREVIOUS values before changing anything - that snapshot is
    what makes the undo real rather than aspirational."""
    params = UpdateCalendarEventParams(**action.params)
    if params.start and params.end and params.end <= params.start:
        raise ActionRejected("The event would end before it starts")

    with _outlook_calendar_client(session, action) as client:
        before = client.get_event(params.event_id)
        after = client.update_event(
            params.event_id, title=params.title, start=params.start,
            end=params.end, attendee_emails=params.attendee_emails,
        )
    return {
        "event_id": after["id"],
        "title": after["title"],
        "url": after["url"],
        "previous": {
            "title": before["title"],
            "start": before["start"].isoformat() if before["start"] else None,
            "end": before["end"].isoformat() if before["end"] else None,
            "attendee_emails": before["attendee_emails"],
        },
    }


def _compensate_outlook_update_event(session: Session, action) -> str:
    from datetime import datetime as _dt

    previous = (action.result or {}).get("previous") or {}
    event_id = (action.result or {}).get("event_id")
    if not event_id or not previous:
        raise ActionRejected("The previous values were not recorded, so this cannot be put back")
    with _outlook_calendar_client(session, action) as client:
        client.update_event(
            event_id,
            title=previous.get("title"),
            start=_dt.fromisoformat(previous["start"]) if previous.get("start") else None,
            end=_dt.fromisoformat(previous["end"]) if previous.get("end") else None,
            attendee_emails=previous.get("attendee_emails"),
        )
    return "Event restored to its previous title, time and attendees"


def _preview_outlook_cancel(params: CancelCalendarEventParams) -> dict:
    return {
        "summary": f"Cancel “{params.title or params.event_id[:20]}”",
        "title": params.title,
        "attendee_count": params.attendee_count,
        "irreversible": True,
        "warning": (
            f"This cancels the meeting and notifies {params.attendee_count} attendee(s). "
            "The cancellation cannot be recalled."
            if params.attendee_count
            else "This cancels the meeting. It cannot be undone."
        ),
    }


def _execute_outlook_cancel_event(session: Session, action) -> dict:
    params = CancelCalendarEventParams(**action.params)
    with _outlook_calendar_client(session, action) as client:
        client.cancel_event(params.event_id, params.comment)
    return {"event_id": params.event_id, "title": params.title, "cancelled": True}


def _verify_outlook_cancel(session: Session, action, result: dict) -> tuple[bool, str]:
    """Confirmed by Microsoft's own state: the event should now read cancelled,
    or be gone entirely."""
    try:
        with _outlook_calendar_client(session, action) as client:
            event = client.get_event(result["event_id"])
    except Exception:  # noqa: BLE001 - a 404 here means it is genuinely gone
        return True, "The event is no longer on the calendar"
    if event.get("cancelled"):
        return True, "Outlook reports the event as cancelled"
    return False, "Cancelled, but the event still reads as active"


_OUTLOOK_CALENDAR_ACTIONS = (
    ActionSpec(
        key="outlook.create_event",
        label="Create a calendar event",
        risk=ActionRisk.MEDIUM,
        params_model=CreateCalendarEventParams,
        external=True,
        preview=_preview_outlook_event,
        execute=_execute_outlook_create_event,
        verify=_verify_outlook_event,
        # Attendees turn a private write into invitations - the same escalation
        # the Google calendar action uses, reused rather than restated.
        risk_for=_risk_for_calendar,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_outlook_create_event,
    ),
    ActionSpec(
        key="outlook.update_event",
        label="Edit a calendar event",
        risk=ActionRisk.MEDIUM,
        params_model=UpdateCalendarEventParams,
        external=True,
        preview=_preview_outlook_update,
        execute=_execute_outlook_update_event,
        verify=_verify_outlook_event,
        risk_for=_risk_for_update,
        # Genuinely undoable because the previous values are captured first.
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_outlook_update_event,
    ),
    ActionSpec(
        key="outlook.cancel_event",
        label="Cancel a calendar event",
        risk=ActionRisk.HIGH,
        params_model=CancelCalendarEventParams,
        external=True,
        preview=_preview_outlook_cancel,
        execute=_execute_outlook_cancel_event,
        verify=_verify_outlook_cancel,
        # No compensate: cancelling notifies every attendee, and that message
        # cannot be unsent. Recreating the event would not undo what they saw.
        reversibility=Reversibility.IRREVERSIBLE,
        autonomy_eligible=False,
    ),
)




# --- Microsoft To Do writes -------------------------------------------------
#
# The gentlest writes in the registry: a task list is private state, so nothing
# here notifies anyone. That is exactly why the risks are LOW and why every one
# of them has a real inverse - completing reopens, editing restores, creating
# deletes, and even a delete can be put back from the snapshot taken first.
#
# They are still external=True, so every one is previewed and confirmed: it is
# the user's real Microsoft account being changed, not Sentinel's copy.

_TASK_IMPORTANCE = ("low", "normal", "high")


class CreateTaskParams(BaseModel):
    list_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime | None = None
    importance: str = Field(default="normal")
    notes: str = Field(default="", max_length=4000)

    @field_validator("importance")
    @classmethod
    def _known_importance(cls, value: str) -> str:
        cleaned = (value or "normal").lower()
        if cleaned not in _TASK_IMPORTANCE:
            raise ValueError(f"importance must be one of {_TASK_IMPORTANCE}")
        return cleaned


class UpdateTaskParams(BaseModel):
    list_id: str = Field(min_length=1, max_length=500)
    task_id: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=300)
    # None is a real value here - it means "clear the due date" - so the
    # executor distinguishes "absent" from "explicitly cleared".
    due_at: datetime | None = None
    clear_due: bool = False
    importance: str | None = None

    @field_validator("importance")
    @classmethod
    def _known_importance(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.lower()
        if cleaned not in _TASK_IMPORTANCE:
            raise ValueError(f"importance must be one of {_TASK_IMPORTANCE}")
        return cleaned


class CompleteTaskParams(BaseModel):
    list_id: str = Field(min_length=1, max_length=500)
    task_id: str = Field(min_length=1, max_length=500)
    completed: bool = True
    title: str = Field(default="", max_length=300)


class DeleteTaskParams(BaseModel):
    list_id: str = Field(min_length=1, max_length=500)
    task_id: str = Field(min_length=1, max_length=500)
    title: str = Field(default="", max_length=300)


def _todo_connection(session: Session, action) -> Connection | None:
    kind, _, owner_id = action.scope_key.partition(":")
    if kind == "personal":
        return session.execute(
            select(Connection).where(
                Connection.workspace_id == action.workspace_id,
                Connection.user_id == uuid.UUID(owner_id),
                Connection.provider == Provider.MICROSOFT_TODO,
                Connection.revoked_at.is_(None),
            )
        ).scalars().first()

    from app.services.channel_authorization import authorized_connections

    for auth in authorized_connections(session, uuid.UUID(owner_id)).values():
        if auth.connection.provider == Provider.MICROSOFT_TODO and auth.connection.revoked_at is None:
            return auth.connection
    return None


def _todo_client(session: Session, action):
    from app.integrations.graph_client import GraphClient
    from app.integrations.microsoft_auth import get_valid_access_token

    connection = _todo_connection(session, action)
    if connection is None:
        raise ActionUnavailable("Microsoft To Do is not connected for this context")
    return GraphClient(get_valid_access_token(session, connection))


def _preview_create_task(params: CreateTaskParams) -> dict:
    when = f" · due {params.due_at:%a %d %b}" if params.due_at else ""
    flag = " · high importance" if params.importance == "high" else ""
    return {"summary": f"Add task “{params.title}”{when}{flag}", "reversible": True}


def _execute_create_task(session: Session, action) -> dict:
    params = CreateTaskParams(**action.params)
    with _todo_client(session, action) as client:
        task = client.create_task(
            params.list_id, title=params.title, due=params.due_at,
            importance=params.importance, body=params.notes or None,
        )
    return {"list_id": params.list_id, "task_id": task["id"], "title": task["title"]}


def _verify_task(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _todo_client(session, action) as client:
            task = client.get_task(result["list_id"], result["task_id"])
    except Exception:  # noqa: BLE001
        return False, "Applied, but Sentinel could not read it back to confirm"
    return True, f"To Do reports “{task['title']}” as {'completed' if task['completed'] else 'open'}"


def _compensate_create_task(session: Session, action) -> str:
    result = action.result or {}
    with _todo_client(session, action) as client:
        client.delete_task(result["list_id"], result["task_id"])
    return "Task removed from To Do"


def _preview_update_task(params: UpdateTaskParams) -> dict:
    changes = []
    if params.title is not None:
        changes.append(f"title → “{params.title}”")
    if params.clear_due:
        changes.append("due date → cleared")
    elif params.due_at is not None:
        changes.append(f"due → {params.due_at:%a %d %b}")
    if params.importance is not None:
        changes.append(f"importance → {params.importance}")
    return {"summary": "Update task: " + ("; ".join(changes) or "no changes"), "changes": changes, "reversible": True}


def _execute_update_task(session: Session, action) -> dict:
    """Captures the previous values first - that snapshot is what makes the undo
    real rather than a promise."""
    params = UpdateTaskParams(**action.params)
    due_arg = None if params.clear_due else (params.due_at if params.due_at is not None else ...)
    with _todo_client(session, action) as client:
        before = client.get_task(params.list_id, params.task_id)
        after = client.update_task(
            params.list_id, params.task_id, title=params.title,
            due=due_arg, importance=params.importance,
        )
    return {
        "list_id": params.list_id,
        "task_id": after["id"],
        "title": after["title"],
        "previous": {
            "title": before["title"],
            "due_at": before["due_at"].isoformat() if before["due_at"] else None,
            "importance": before["importance"],
        },
    }


def _compensate_update_task(session: Session, action) -> str:
    from datetime import datetime as _dt

    result = action.result or {}
    previous = result.get("previous") or {}
    if not previous:
        raise ActionRejected("The previous values were not recorded, so this cannot be put back")
    with _todo_client(session, action) as client:
        client.update_task(
            result["list_id"], result["task_id"],
            title=previous.get("title"),
            due=_dt.fromisoformat(previous["due_at"]) if previous.get("due_at") else None,
            importance=previous.get("importance"),
        )
    return "Task restored to its previous title, due date and importance"


def _preview_complete_task(params: CompleteTaskParams) -> dict:
    verb = "Complete" if params.completed else "Reopen"
    return {"summary": f"{verb} “{params.title or params.task_id[:20]}”", "reversible": True}


def _execute_complete_task(session: Session, action) -> dict:
    params = CompleteTaskParams(**action.params)
    with _todo_client(session, action) as client:
        task = client.update_task(params.list_id, params.task_id, completed=params.completed)
    return {"list_id": params.list_id, "task_id": task["id"], "completed": params.completed, "title": task["title"]}


def _verify_complete_task(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _todo_client(session, action) as client:
            task = client.get_task(result["list_id"], result["task_id"])
    except Exception:  # noqa: BLE001
        return False, "Applied, but Sentinel could not read it back to confirm"
    return task["completed"] == result["completed"], f"To Do reports completed={task['completed']}"


def _compensate_complete_task(session: Session, action) -> str:
    params = CompleteTaskParams(**action.params)
    with _todo_client(session, action) as client:
        client.update_task(params.list_id, params.task_id, completed=not params.completed)
    return f"Task set back to {'open' if params.completed else 'completed'}"


def _preview_delete_task(params: DeleteTaskParams) -> dict:
    return {
        "summary": f"Delete “{params.title or params.task_id[:20]}”",
        "warning": "The task is removed from To Do. Undo recreates it from the recorded values as a new task.",
        "reversible": True,
    }


def _execute_delete_task(session: Session, action) -> dict:
    """Reads the task BEFORE deleting it, so the undo has something to restore
    from. Without that snapshot the delete would be unrecoverable."""
    params = DeleteTaskParams(**action.params)
    with _todo_client(session, action) as client:
        before = client.get_task(params.list_id, params.task_id)
        client.delete_task(params.list_id, params.task_id)
    return {
        "list_id": params.list_id,
        "task_id": params.task_id,
        "deleted": True,
        "previous": {
            "title": before["title"],
            "due_at": before["due_at"].isoformat() if before["due_at"] else None,
            "importance": before["importance"],
            "body": before["body"],
        },
    }


def _verify_delete_task(session: Session, action, result: dict) -> tuple[bool, str]:
    """Confirmed by absence: reading it back should fail."""
    try:
        with _todo_client(session, action) as client:
            client.get_task(result["list_id"], result["task_id"])
    except Exception:  # noqa: BLE001 - a 404 here is the success case
        return True, "The task is no longer in To Do"
    return False, "Deleted, but the task can still be read back"


def _compensate_delete_task(session: Session, action) -> str:
    from datetime import datetime as _dt

    result = action.result or {}
    previous = result.get("previous") or {}
    if not previous:
        raise ActionRejected("The task's contents were not recorded, so it cannot be restored")
    with _todo_client(session, action) as client:
        client.create_task(
            result["list_id"], title=previous["title"],
            due=_dt.fromisoformat(previous["due_at"]) if previous.get("due_at") else None,
            importance=previous.get("importance") or "normal",
            body=previous.get("body") or None,
        )
    # Deliberately precise: this is a restoration of the CONTENT, not a revival
    # of the original row - the identifier is new.
    return "Task recreated from the recorded values (a new task, since the original was deleted)"


_TODO_ACTIONS = (
    ActionSpec(
        key="todo.create_task",
        label="Add a task",
        risk=ActionRisk.LOW,
        params_model=CreateTaskParams,
        external=True,
        preview=_preview_create_task,
        execute=_execute_create_task,
        verify=_verify_task,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_create_task,
    ),
    ActionSpec(
        key="todo.update_task",
        label="Edit a task",
        risk=ActionRisk.LOW,
        params_model=UpdateTaskParams,
        external=True,
        preview=_preview_update_task,
        execute=_execute_update_task,
        verify=_verify_task,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_update_task,
    ),
    ActionSpec(
        key="todo.complete_task",
        label="Complete or reopen a task",
        risk=ActionRisk.LOW,
        params_model=CompleteTaskParams,
        external=True,
        preview=_preview_complete_task,
        execute=_execute_complete_task,
        verify=_verify_complete_task,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_complete_task,
    ),
    ActionSpec(
        key="todo.delete_task",
        label="Delete a task",
        # Higher than the others: deletion loses state the others only change,
        # and the restore is a new task rather than the original.
        risk=ActionRisk.MEDIUM,
        params_model=DeleteTaskParams,
        external=True,
        preview=_preview_delete_task,
        execute=_execute_delete_task,
        verify=_verify_delete_task,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_delete_task,
    ),
)




# --- OneDrive and OneNote writes -------------------------------------------
#
# Private-state writes, like To Do: nothing here notifies anyone, so the risks
# are low. What differs is how honestly each one can be taken back:
#
#   create folder / upload / create page   COMPENSATABLE - delete what was made
#   rename / move                          COMPENSATABLE - the old name/parent is recorded
#   append to a page                       COMPENSATABLE - the previous HTML is captured first
#   delete a drive item                    IRREVERSIBLE here - Graph moves it to the
#                                          OneDrive recycle bin, which this API cannot
#                                          restore from, so no undo button is offered

# A OneNote page's previous HTML is kept only to make undo real. Beyond this it
# is not worth storing on an action row, and an oversized page simply loses the
# undo rather than silently truncating the restore.
MAX_UNDO_SNAPSHOT_CHARS = 200_000
# Uploads travel as an action parameter, so they are small text documents by
# construction - not a general file-transfer path.
MAX_UPLOAD_CHARS = 100_000

_SAFE_NAME_RE = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]+$')


class CreateFolderParams(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _safe(cls, value: str) -> str:
        cleaned = value.strip()
        if not _SAFE_NAME_RE.match(cleaned):
            raise ValueError("A folder name cannot contain < > : \" / \\ | ? *")
        return cleaned


class UploadTextParams(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=MAX_UPLOAD_CHARS)
    parent_id: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _safe(cls, value: str) -> str:
        cleaned = value.strip()
        if not _SAFE_NAME_RE.match(cleaned):
            raise ValueError("A file name cannot contain < > : \" / \\ | ? *")
        return cleaned


class RenameItemParams(BaseModel):
    item_id: str = Field(min_length=1, max_length=500)
    new_name: str = Field(min_length=1, max_length=255)

    @field_validator("new_name")
    @classmethod
    def _safe(cls, value: str) -> str:
        cleaned = value.strip()
        if not _SAFE_NAME_RE.match(cleaned):
            raise ValueError("A name cannot contain < > : \" / \\ | ? *")
        return cleaned


class MoveItemParams(BaseModel):
    item_id: str = Field(min_length=1, max_length=500)
    new_parent_id: str = Field(min_length=1, max_length=500)
    name: str = Field(default="", max_length=255)


class DeleteItemParams(BaseModel):
    item_id: str = Field(min_length=1, max_length=500)
    name: str = Field(default="", max_length=255)
    is_folder: bool = False


class CreateNotePageParams(BaseModel):
    section_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=50_000)


class AppendNotePageParams(BaseModel):
    page_id: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50_000)
    title: str = Field(default="", max_length=300)


def _ms_connection(session: Session, action, provider: Provider) -> Connection | None:
    kind, _, owner_id = action.scope_key.partition(":")
    if kind == "personal":
        return session.execute(
            select(Connection).where(
                Connection.workspace_id == action.workspace_id,
                Connection.user_id == uuid.UUID(owner_id),
                Connection.provider == provider,
                Connection.revoked_at.is_(None),
            )
        ).scalars().first()

    from app.services.channel_authorization import authorized_connections

    for auth in authorized_connections(session, uuid.UUID(owner_id)).values():
        if auth.connection.provider == provider and auth.connection.revoked_at is None:
            return auth.connection
    return None


def _drive_client(session: Session, action):
    from app.integrations.graph_client import GraphClient
    from app.integrations.microsoft_auth import get_valid_access_token

    connection = _ms_connection(session, action, Provider.MICROSOFT_ONEDRIVE)
    if connection is None:
        raise ActionUnavailable("OneDrive is not connected for this context")
    return GraphClient(get_valid_access_token(session, connection))


def _note_client(session: Session, action):
    from app.integrations.graph_client import GraphClient
    from app.integrations.microsoft_auth import get_valid_access_token

    connection = _ms_connection(session, action, Provider.MICROSOFT_ONENOTE)
    if connection is None:
        raise ActionUnavailable("OneNote is not connected for this context")
    return GraphClient(get_valid_access_token(session, connection))


# --- OneDrive ---------------------------------------------------------------

def _preview_create_folder(params: CreateFolderParams) -> dict:
    where = "in the selected folder" if params.parent_id else "at the top of your drive"
    return {"summary": f"Create folder “{params.name}” {where}", "reversible": True}


def _execute_create_folder(session: Session, action) -> dict:
    params = CreateFolderParams(**action.params)
    with _drive_client(session, action) as client:
        item = client.create_folder(params.name, params.parent_id)
    return {"item_id": item["id"], "name": item["name"], "url": item["url"]}


def _verify_drive_item(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _drive_client(session, action) as client:
            item = client.get_item(result["item_id"])
    except Exception:  # noqa: BLE001
        return False, "Applied, but Sentinel could not read it back to confirm"
    return True, f"OneDrive reports “{item['name']}”"


def _compensate_delete_drive_item(session: Session, action) -> str:
    """Shared undo for anything this created: remove what was made."""
    result = action.result or {}
    item_id = result.get("item_id")
    if not item_id:
        raise ActionRejected("No item id was recorded, so it cannot be removed")
    with _drive_client(session, action) as client:
        client.delete_item(item_id)
    return "Removed from OneDrive (it is in the recycle bin)"


def _preview_upload_text(params: UploadTextParams) -> dict:
    return {
        "summary": f"Create “{params.name}” in OneDrive ({len(params.content)} characters)",
        "reversible": True,
    }


def _execute_upload_text(session: Session, action) -> dict:
    params = UploadTextParams(**action.params)
    with _drive_client(session, action) as client:
        item = client.upload_text_file(params.name, params.content, params.parent_id)
    return {"item_id": item["id"], "name": item["name"], "url": item["url"]}


def _preview_rename_item(params: RenameItemParams) -> dict:
    return {"summary": f"Rename to “{params.new_name}”", "reversible": True}


def _execute_rename_item(session: Session, action) -> dict:
    params = RenameItemParams(**action.params)
    with _drive_client(session, action) as client:
        before = client.get_item(params.item_id)
        after = client.rename_item(params.item_id, params.new_name)
    return {"item_id": after["id"], "name": after["name"], "previous_name": before["name"]}


def _compensate_rename_item(session: Session, action) -> str:
    result = action.result or {}
    previous = result.get("previous_name")
    if not previous:
        raise ActionRejected("The previous name was not recorded, so it cannot be put back")
    with _drive_client(session, action) as client:
        client.rename_item(result["item_id"], previous)
    return f"Renamed back to “{previous}”"


def _preview_move_item(params: MoveItemParams) -> dict:
    return {"summary": f"Move “{params.name or params.item_id[:16]}” to another folder", "reversible": True}


def _execute_move_item(session: Session, action) -> dict:
    params = MoveItemParams(**action.params)
    with _drive_client(session, action) as client:
        before = client.get_item(params.item_id)
        after = client.move_item(params.item_id, params.new_parent_id)
    return {"item_id": after["id"], "name": after["name"], "previous_parent_id": before["parent_id"]}


def _compensate_move_item(session: Session, action) -> str:
    result = action.result or {}
    previous_parent = result.get("previous_parent_id")
    if not previous_parent:
        raise ActionRejected("The previous folder was not recorded, so it cannot be put back")
    with _drive_client(session, action) as client:
        client.move_item(result["item_id"], previous_parent)
    return "Moved back to its previous folder"


def _preview_delete_item(params: DeleteItemParams) -> dict:
    kind = "folder and everything in it" if params.is_folder else "file"
    return {
        "summary": f"Delete {kind}: “{params.name or params.item_id[:16]}”",
        "irreversible": True,
        "warning": (
            f"This moves the {kind} to the OneDrive recycle bin. Sentinel cannot "
            "restore it - you would need to recover it in OneDrive itself."
        ),
    }


def _execute_delete_item(session: Session, action) -> dict:
    params = DeleteItemParams(**action.params)
    with _drive_client(session, action) as client:
        client.delete_item(params.item_id)
    return {"item_id": params.item_id, "name": params.name, "deleted": True}


def _verify_delete_item(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _drive_client(session, action) as client:
            client.get_item(result["item_id"])
    except Exception:  # noqa: BLE001 - not found is the success case
        return True, "The item is no longer in OneDrive (it is in the recycle bin)"
    return False, "Deleted, but the item can still be read back"


# --- OneNote ----------------------------------------------------------------

def _preview_create_page(params: CreateNotePageParams) -> dict:
    return {"summary": f"Create note “{params.title}”", "chars": len(params.body), "reversible": True}


def _execute_create_page(session: Session, action) -> dict:
    params = CreateNotePageParams(**action.params)
    with _note_client(session, action) as client:
        page = client.create_page(params.section_id, params.title, params.body)
    return {"page_id": page["id"], "title": page["title"], "url": page["url"]}


def _verify_note_page(session: Session, action, result: dict) -> tuple[bool, str]:
    """OneNote is eventually consistent: a page created a moment ago is
    sometimes not readable on the first try, which was reporting genuinely
    successful creates as `unknown` (observed live, then measured - the delay is
    variable, usually zero). So this retries briefly instead of failing fast,
    and reads METADATA rather than full content, which is cheaper.

    It still reports honestly if the page never appears - an unverified write is
    never dressed up as a success."""
    import time as _time

    page_id = result["page_id"]
    for attempt in range(3):
        try:
            with _note_client(session, action) as client:
                page = client.get_page(page_id)
            return True, f"OneNote has the page “{page.get('title') or result.get('title') or ''}”".strip()
        except Exception:  # noqa: BLE001 - not visible yet, or genuinely absent
            if attempt < 2:
                _time.sleep(1.5)
    return False, "Applied, but Sentinel could not read the page back to confirm"


def _compensate_create_page(session: Session, action) -> str:
    result = action.result or {}
    page_id = result.get("page_id")
    if not page_id:
        raise ActionRejected("No page id was recorded, so it cannot be removed")
    with _note_client(session, action) as client:
        client.delete_page(page_id)
    return "Page deleted from OneNote"


def _preview_append_page(params: AppendNotePageParams) -> dict:
    return {
        "summary": f"Add to “{params.title or params.page_id[:16]}” ({len(params.content)} characters)",
        "reversible": True,
    }


def _execute_append_page(session: Session, action) -> dict:
    """Captures the page's current HTML before appending, which is the only way
    an append can honestly offer an undo."""
    params = AppendNotePageParams(**action.params)
    with _note_client(session, action) as client:
        try:
            before = client.page_content(params.page_id)
        except Exception:  # noqa: BLE001 - no snapshot means no undo, said plainly
            before = None
        client.patch_page(
            params.page_id,
            [{"target": "body", "action": "append", "content": f"<p>{params.content}</p>"}],
        )
    snapshot = before if (before and len(before) <= MAX_UNDO_SNAPSHOT_CHARS) else None
    return {
        "page_id": params.page_id,
        "title": params.title,
        "previous_html": snapshot,
        # Stated on the record rather than inferred later, so the audit trail
        # shows whether an undo was ever possible for this run.
        "undo_available": snapshot is not None,
    }


def _compensate_append_page(session: Session, action) -> str:
    result = action.result or {}
    previous = result.get("previous_html")
    if not previous:
        raise ActionRejected(
            "The page's previous contents were not captured (too large, or unreadable), "
            "so this cannot be put back"
        )
    with _note_client(session, action) as client:
        client.patch_page(result["page_id"], [{"target": "body", "action": "replace", "content": previous}])
    return "Page restored to its contents before the addition"



class CreateNotebookParams(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class CreateSectionParams(BaseModel):
    notebook_id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=128)


def _preview_create_notebook(params: CreateNotebookParams) -> dict:
    return {"summary": f"Create notebook “{params.name}”", "reversible": False,
            "warning": "OneNote does not let Sentinel delete a notebook, so this cannot be undone here."}


def _execute_create_notebook(session: Session, action) -> dict:
    params = CreateNotebookParams(**action.params)
    with _note_client(session, action) as client:
        nb = client.create_notebook(params.name)
    return {"notebook_id": nb["id"], "name": nb["name"], "url": nb["url"]}


def _verify_create_notebook(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _note_client(session, action) as client:
            names = {n["id"]: n["name"] for n in client.notebooks()}
    except Exception:  # noqa: BLE001
        return False, "Created, but Sentinel could not list notebooks to confirm"
    if result["notebook_id"] in names:
        return True, f"OneNote lists the notebook “{names[result['notebook_id']]}”"
    return False, "Created, but the notebook was not found when listing"


def _preview_create_section(params: CreateSectionParams) -> dict:
    return {"summary": f"Create section “{params.name}”", "reversible": False,
            "warning": "OneNote does not let Sentinel delete a section, so this cannot be undone here."}


def _execute_create_section(session: Session, action) -> dict:
    params = CreateSectionParams(**action.params)
    with _note_client(session, action) as client:
        sec = client.create_section(params.notebook_id, params.name)
    return {"section_id": sec["id"], "name": sec["name"], "notebook_id": params.notebook_id}


def _verify_create_section(session: Session, action, result: dict) -> tuple[bool, str]:
    try:
        with _note_client(session, action) as client:
            ids = {s["id"] for s in client.sections(result["notebook_id"])}
    except Exception:  # noqa: BLE001
        return False, "Created, but Sentinel could not list sections to confirm"
    return (result["section_id"] in ids), (
        f"OneNote lists the section “{result['name']}”" if result["section_id"] in ids
        else "Created, but the section was not found when listing"
    )


_ONENOTE_STRUCTURE_ACTIONS = (
    ActionSpec(
        key="onenote.create_notebook",
        label="Create a notebook",
        risk=ActionRisk.LOW,
        params_model=CreateNotebookParams,
        external=True,
        preview=_preview_create_notebook,
        execute=_execute_create_notebook,
        verify=_verify_create_notebook,
        # Graph offers no delete for consumer notebooks, so there is genuinely
        # no inverse - and therefore no undo button, per this module's rule.
        reversibility=Reversibility.IRREVERSIBLE,
    ),
    ActionSpec(
        key="onenote.create_section",
        label="Create a section",
        risk=ActionRisk.LOW,
        params_model=CreateSectionParams,
        external=True,
        preview=_preview_create_section,
        execute=_execute_create_section,
        verify=_verify_create_section,
        reversibility=Reversibility.IRREVERSIBLE,
    ),
)


_DRIVE_NOTE_ACTIONS = (
    ActionSpec(
        key="onedrive.create_folder",
        label="Create a folder",
        risk=ActionRisk.LOW,
        params_model=CreateFolderParams,
        external=True,
        preview=_preview_create_folder,
        execute=_execute_create_folder,
        verify=_verify_drive_item,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_delete_drive_item,
    ),
    ActionSpec(
        key="onedrive.upload_text",
        label="Create a text file",
        risk=ActionRisk.LOW,
        params_model=UploadTextParams,
        external=True,
        preview=_preview_upload_text,
        execute=_execute_upload_text,
        verify=_verify_drive_item,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_delete_drive_item,
    ),
    ActionSpec(
        key="onedrive.rename_item",
        label="Rename a file or folder",
        risk=ActionRisk.LOW,
        params_model=RenameItemParams,
        external=True,
        preview=_preview_rename_item,
        execute=_execute_rename_item,
        verify=_verify_drive_item,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_rename_item,
    ),
    ActionSpec(
        key="onedrive.move_item",
        label="Move a file or folder",
        risk=ActionRisk.LOW,
        params_model=MoveItemParams,
        external=True,
        preview=_preview_move_item,
        execute=_execute_move_item,
        verify=_verify_drive_item,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_move_item,
    ),
    ActionSpec(
        key="onedrive.delete_item",
        label="Delete a file or folder",
        # Deleting a folder takes its contents with it, which is why this is the
        # one drive action priced above LOW.
        risk=ActionRisk.MEDIUM,
        params_model=DeleteItemParams,
        external=True,
        preview=_preview_delete_item,
        execute=_execute_delete_item,
        verify=_verify_delete_item,
        # No compensate: Graph moves the item to the OneDrive recycle bin and
        # offers this API no way to restore it, so no undo button is offered.
        reversibility=Reversibility.IRREVERSIBLE,
        autonomy_eligible=False,
    ),
    ActionSpec(
        key="onenote.create_page",
        label="Create a note",
        risk=ActionRisk.LOW,
        params_model=CreateNotePageParams,
        external=True,
        preview=_preview_create_page,
        execute=_execute_create_page,
        verify=_verify_note_page,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_create_page,
    ),
    ActionSpec(
        key="onenote.append_page",
        label="Add to a note",
        risk=ActionRisk.LOW,
        params_model=AppendNotePageParams,
        external=True,
        preview=_preview_append_page,
        execute=_execute_append_page,
        verify=_verify_note_page,
        # Compensatable only because the previous HTML is captured first; the
        # compensation refuses outright when that snapshot is missing.
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_append_page,
    ),
)


# --- Zoom meeting writes ----------------------------------------------------
#
# The same three-verb shape as the Outlook Calendar actions, and the same honest
# difference between them in what can be taken back:
#   create  COMPENSATABLE   the meeting can be deleted
#   update  COMPENSATABLE   the previous values are captured first, so they go back
#   delete  IRREVERSIBLE    Zoom notifies registrants, and that cannot be unsent
#
# Risk does NOT escalate on attendees the way the calendar actions do, and that
# is deliberate rather than an oversight: creating a Zoom meeting invites nobody.
# It mints a join link. Zoom only notifies people who were already registered on
# an existing meeting, which is why `delete` is the one that carries the warning.


class CreateZoomMeetingParams(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    start: datetime
    duration: int = Field(default=30, ge=1, le=24 * 60)
    agenda: str = Field(default="", max_length=2000)
    timezone_name: str = Field(default="UTC", max_length=64)


class UpdateZoomMeetingParams(BaseModel):
    meeting_id: str = Field(min_length=1, max_length=64)
    topic: str | None = Field(default=None, max_length=200)
    start: datetime | None = None
    duration: int | None = Field(default=None, ge=1, le=24 * 60)
    agenda: str | None = Field(default=None, max_length=2000)


class DeleteZoomMeetingParams(BaseModel):
    meeting_id: str = Field(min_length=1, max_length=64)
    topic: str = Field(default="", max_length=200)
    # Whether Zoom mails the registrants. Carried so the preview can say which
    # of the two things is about to happen, and the audit record proves it.
    notify: bool = True


def _zoom_connection(session: Session, action) -> Connection | None:
    """The Zoom account this action may write to, resolved from the action's own
    scope - never from the caller. Identical resolution to every other provider."""
    kind, _, owner_id = action.scope_key.partition(":")
    if kind == "personal":
        return session.execute(
            select(Connection).where(
                Connection.workspace_id == action.workspace_id,
                Connection.user_id == uuid.UUID(owner_id),
                Connection.provider == Provider.ZOOM,
                Connection.revoked_at.is_(None),
            )
        ).scalars().first()

    from app.services.channel_authorization import authorized_connections

    for auth in authorized_connections(session, uuid.UUID(owner_id)).values():
        if auth.connection.provider == Provider.ZOOM and auth.connection.revoked_at is None:
            return auth.connection
    return None


def _zoom_client(session: Session, action):
    from app.integrations.zoom_auth import get_valid_access_token as zoom_token
    from app.integrations.zoom_client import ZoomClient

    connection = _zoom_connection(session, action)
    if connection is None:
        raise ActionUnavailable("No Zoom account is authorized for this context")
    return ZoomClient(zoom_token(session, connection))


def _preview_zoom_create(params: CreateZoomMeetingParams) -> dict:
    return {
        "summary": f"Schedule “{params.topic}” on {params.start:%a %d %b at %H:%M} for {params.duration} min",
        "topic": params.topic,
        "when": f"{params.start:%a %d %b %H:%M} ({params.duration} min)",
        # Said explicitly because it is the question a user actually has, and the
        # answer differs from the calendar actions sitting next to it.
        "notifies": False,
        "effect": "Creates a real Zoom meeting and returns its join link. Nobody is invited or notified.",
    }


def _execute_zoom_create(session: Session, action) -> dict:
    params = CreateZoomMeetingParams(**action.params)
    with _zoom_client(session, action) as client:
        meeting = client.create_meeting(
            topic=params.topic, start=params.start, duration=params.duration,
            agenda=params.agenda, timezone_name=params.timezone_name,
        )
    return {
        "meeting_id": meeting["id"],
        "topic": meeting["topic"],
        "join_url": meeting["join_url"],
        "start": meeting["start"].isoformat() if meeting["start"] else None,
    }


def _verify_zoom_meeting(session: Session, action, result: dict) -> tuple[bool, str]:
    """Execution is not completion: the meeting is read back from Zoom."""
    try:
        with _zoom_client(session, action) as client:
            meeting = client.meeting(result["meeting_id"])
    except Exception:  # noqa: BLE001 - a failed read-back is "cannot confirm"
        return False, "Applied, but Sentinel could not read it back to confirm"
    when = f" at {meeting['start']:%a %d %b %H:%M}" if meeting["start"] else ""
    return True, f"Zoom has “{meeting['topic']}”{when}"


def _compensate_zoom_create(session: Session, action) -> str:
    result = action.result or {}
    meeting_id = result.get("meeting_id")
    if not meeting_id:
        raise ActionRejected("No meeting id was recorded, so it cannot be removed")
    with _zoom_client(session, action) as client:
        # notify=False: nobody was told it existed, so nobody is told it is gone.
        client.delete_meeting(meeting_id, notify=False)
    return "The meeting was deleted from Zoom"


def _preview_zoom_update(params: UpdateZoomMeetingParams) -> dict:
    changes = []
    if params.topic is not None:
        changes.append(f"topic → “{params.topic}”")
    if params.start is not None:
        changes.append(f"start → {params.start:%a %d %b %H:%M}")
    if params.duration is not None:
        changes.append(f"duration → {params.duration} min")
    if params.agenda is not None:
        changes.append("agenda updated")
    return {
        "summary": "Update the meeting: " + ("; ".join(changes) or "no changes"),
        "changes": changes,
        "reversible": True,
    }


def _execute_zoom_update(session: Session, action) -> dict:
    """Reads the CURRENT values before changing anything - that snapshot is what
    makes the undo real rather than aspirational."""
    params = UpdateZoomMeetingParams(**action.params)
    with _zoom_client(session, action) as client:
        before = client.meeting(params.meeting_id)
        client.update_meeting(
            params.meeting_id, topic=params.topic, start=params.start,
            duration=params.duration, agenda=params.agenda,
        )
    return {
        "meeting_id": params.meeting_id,
        "topic": params.topic or before["topic"],
        "previous": {
            "topic": before["topic"],
            "start": before["start"].isoformat() if before["start"] else None,
            "duration": before["duration"],
            "agenda": before["agenda"],
        },
    }


def _compensate_zoom_update(session: Session, action) -> str:
    from datetime import datetime as _dt

    result = action.result or {}
    previous = result.get("previous") or {}
    if not previous:
        raise ActionRejected("The previous values were not recorded, so this cannot be put back")
    with _zoom_client(session, action) as client:
        client.update_meeting(
            result["meeting_id"],
            topic=previous.get("topic"),
            start=_dt.fromisoformat(previous["start"]) if previous.get("start") else None,
            duration=previous.get("duration"),
            agenda=previous.get("agenda"),
        )
    return "The meeting was restored to its previous topic, time and agenda"


def _preview_zoom_delete(params: DeleteZoomMeetingParams) -> dict:
    return {
        "summary": f"Delete “{params.topic or params.meeting_id}”",
        "topic": params.topic,
        "irreversible": True,
        "warning": (
            "This deletes the Zoom meeting and emails everyone registered for it. "
            "The join link stops working immediately and the notification cannot be recalled."
            if params.notify
            else "This deletes the Zoom meeting. The join link stops working immediately and it cannot be undone."
        ),
    }


def _execute_zoom_delete(session: Session, action) -> dict:
    params = DeleteZoomMeetingParams(**action.params)
    with _zoom_client(session, action) as client:
        client.delete_meeting(params.meeting_id, notify=params.notify)
    return {"meeting_id": params.meeting_id, "topic": params.topic, "deleted": True}


def _verify_zoom_delete(session: Session, action, result: dict) -> tuple[bool, str]:
    """Confirmed by absence: reading it back should fail."""
    try:
        with _zoom_client(session, action) as client:
            client.meeting(result["meeting_id"])
    except Exception:  # noqa: BLE001 - a 404 here is the success case
        return True, "The meeting is no longer in Zoom"
    return False, "Deleted, but the meeting can still be read back"


_ZOOM_ACTIONS = (
    ActionSpec(
        key="zoom.create_meeting",
        label="Schedule a Zoom meeting",
        risk=ActionRisk.MEDIUM,
        params_model=CreateZoomMeetingParams,
        external=True,
        preview=_preview_zoom_create,
        execute=_execute_zoom_create,
        verify=_verify_zoom_meeting,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_zoom_create,
    ),
    ActionSpec(
        key="zoom.update_meeting",
        label="Edit a Zoom meeting",
        risk=ActionRisk.MEDIUM,
        params_model=UpdateZoomMeetingParams,
        external=True,
        preview=_preview_zoom_update,
        execute=_execute_zoom_update,
        verify=_verify_zoom_meeting,
        reversibility=Reversibility.COMPENSATABLE,
        compensate=_compensate_zoom_update,
    ),
    ActionSpec(
        key="zoom.delete_meeting",
        label="Delete a Zoom meeting",
        risk=ActionRisk.HIGH,
        params_model=DeleteZoomMeetingParams,
        external=True,
        preview=_preview_zoom_delete,
        execute=_execute_zoom_delete,
        verify=_verify_zoom_delete,
        # No compensate, on purpose. Recreating the meeting would mint a NEW
        # join link and would not unsend the cancellation registrants received -
        # so this module's rule applies: no inverse means IRREVERSIBLE, stated
        # plainly, rather than an undo button that cannot deliver.
        reversibility=Reversibility.IRREVERSIBLE,
        autonomy_eligible=False,
    ),
)


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
            reversibility=Reversibility.REVERSIBLE,
            compensate=_compensate_create_commitment,
            autonomy_eligible=True,
        ),
        ActionSpec(
            key="commitment.resolve",
            label="Mark a commitment done",
            risk=ActionRisk.LOW,
            params_model=ResolveCommitmentParams,
            preview=_preview_resolve,
            execute=_execute_resolve_commitment,
            verify=_verify_resolve_commitment,
            reversibility=Reversibility.REVERSIBLE,
            compensate=_compensate_resolve_commitment,
        ),
        ActionSpec(
            key="goal.create",
            label="Set a goal",
            risk=ActionRisk.LOW,
            params_model=CreateGoalParams,
            preview=_preview_goal,
            execute=_execute_create_goal,
            verify=_verify_create_goal,
            reversibility=Reversibility.REVERSIBLE,
            compensate=_compensate_create_goal,
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
            reversibility=Reversibility.REVERSIBLE,
            compensate=_compensate_snooze,
            autonomy_eligible=True,
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
            risk_for=_risk_for_calendar,
            # The provider offers an inverse, so this is compensatable -
            # but not reversible: an invitation that was seen cannot be unseen.
            reversibility=Reversibility.COMPENSATABLE,
            compensate=_compensate_calendar_event,
        ),
        ActionSpec(
            key="email.draft",
            label="Write a draft",
            risk=ActionRisk.LOW,
            params_model=DraftEmailParams,
            preview=_preview_draft,
            execute=_execute_draft,
            verify=_verify_draft,
            reversibility=Reversibility.REVERSIBLE,
            compensate=_compensate_draft,
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
            # Why this stays unavailable: there is no inverse. A sent message
            # cannot be recalled, so an approval could never be undone.
            reversibility=Reversibility.IRREVERSIBLE,
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
            reversibility=Reversibility.COMPENSATABLE,  # an issue can be closed
        ),
        # Microsoft 365 workspace writes, defined above. Spread here so the
        # allow-list stays one dict - a key absent from it cannot be proposed,
        # approved or executed, whatever any caller or model asks for.
        *_OUTLOOK_ACTIONS,
        *_OUTLOOK_CALENDAR_ACTIONS,
        *_TODO_ACTIONS,
        *_DRIVE_NOTE_ACTIONS,
        *_ONENOTE_STRUCTURE_ACTIONS,
        *_ZOOM_ACTIONS,
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
