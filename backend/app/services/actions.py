"""Propose, authorize, approve, execute once, verify, record.

Each of those is a separate step here, and the separation is the safety
model rather than ceremony:

    propose    the registry accepts the type; Pydantic accepts the params;
               the scope accepts the action. Nothing has happened yet.
    authorize  RBAC for *this action*, which is not the same question as
               whether the scope may read the resource.
    approve    a person, recorded by id and time. Skipped only for LOW-risk
               internal reversible actions, and never for anything external.
    execute    exactly once, guarded by a unique idempotency key and a status
               transition that acts as a lock.
    verify     read the change back. Execution is not completion.
    record     what happened, including when it didn't.

## The model never reaches this module's decisions

An LLM may fill in `action_type` and `params` and nothing else. Both are then
validated against the registry and re-validated against the scope at
execution time. Authorization, approval, execution and verification are
plain Python that never consults a model, so a prompt injection can at most
propose something the server will refuse.

## Failure is honest

A provider that refuses leaves FAILED with its message. A provider that
accepted but could not be confirmed leaves UNKNOWN - deliberately not FAILED,
because the change may exist and telling someone it failed invites them to
make it twice.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.action import Action, ActionStatus
from app.models.team import ChannelRole, TeamMembership
from app.services.action_registry import (
    ActionRejected,
    ActionSpec,
    ActionUnavailable,
    get_spec,
    validate_params,
)

logger = structlog.get_logger("sentinel.actions")

_TERMINAL = (
    ActionStatus.SUCCEEDED,
    ActionStatus.FAILED,
    ActionStatus.UNKNOWN,
    ActionStatus.REJECTED,
    ActionStatus.CANCELLED,
)


class NotAuthorized(ActionRejected):
    pass


# --- propose ---------------------------------------------------------------


def propose_action(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    scope_key: str,
    action_type: str,
    params: dict,
    user_id: uuid.UUID,
    reason: str | None = None,
    source_kind: str | None = None,
    source_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> Action:
    """Create a proposal. Nothing outside Sentinel happens here.

    Everything that could be wrong is caught before a row exists: an unknown
    type, malformed parameters, a scope that may not run this action, or a
    caller without the role it requires.
    """
    spec = get_spec(action_type)
    if not spec.available:
        raise ActionUnavailable(spec.unavailable_reason or f"{spec.key} is not available")

    scope_kind = scope_key.partition(":")[0]
    if scope_kind not in spec.scopes:
        raise ActionRejected(f"{spec.label} cannot be run in a {scope_kind} context")

    validated = validate_params(spec, params)
    _assert_authorized(session, spec, scope_key, user_id)

    key = idempotency_key or _derive_idempotency_key(scope_key, action_type, validated.model_dump(mode="json"))

    # A proposal that already exists is returned rather than duplicated -
    # asking twice is not the same as acting twice, and re-proposing the
    # identical thing should be harmless.
    existing = session.execute(select(Action).where(Action.idempotency_key == key)).scalar_one_or_none()
    if existing is not None:
        return existing

    action = Action(
        workspace_id=workspace_id,
        scope_key=scope_key,
        action_type=spec.key,
        risk=spec.risk,
        status=ActionStatus.AWAITING_APPROVAL if spec.needs_approval else ActionStatus.APPROVED,
        params=validated.model_dump(mode="json"),
        preview=spec.preview(validated) if spec.preview else {},
        reason=reason,
        source_kind=source_kind,
        source_id=source_id,
        requested_by_user_id=user_id,
        idempotency_key=key,
    )
    # A LOW-risk internal action is pre-approved by the request itself, and
    # the record says who that was - the audit trail never has a blank
    # approver just because no dialog appeared.
    if not spec.needs_approval:
        action.approved_by_user_id = user_id
        action.approved_at = datetime.now(timezone.utc)

    session.add(action)
    try:
        session.commit()
    except IntegrityError:
        # Two identical proposals raced. The other one won; use it.
        session.rollback()
        return session.execute(select(Action).where(Action.idempotency_key == key)).scalar_one()

    session.refresh(action)
    logger.info(
        "action_proposed",
        action_id=str(action.id), type=spec.key, scope=scope_key, risk=spec.risk.value,
        needs_approval=spec.needs_approval,
    )
    return action


def _derive_idempotency_key(scope_key: str, action_type: str, params: dict) -> str:
    """Same scope + same action + same parameters = the same intent.

    Derived rather than random so a double-clicked Confirm and a retried
    request collide naturally. A caller that genuinely wants a second
    identical event passes its own key.
    """
    raw = json.dumps({"s": scope_key, "t": action_type, "p": params}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:120]


# --- authorize -------------------------------------------------------------


def _assert_authorized(session: Session, spec: ActionSpec, scope_key: str, user_id: uuid.UUID) -> None:
    """Whether this person may run this action - a separate question from
    whether the scope may read the underlying resource.

    Read access is not write access. A channel member can see everything the
    channel is authorized for; several actions here still require a channel
    admin, and that requirement is declared per action rather than inferred.
    """
    kind, _, owner_id = scope_key.partition(":")

    if kind == "personal":
        if str(user_id) != owner_id:
            raise NotAuthorized("You can only act in your own personal context")
        return

    if kind != "channel":
        raise ActionRejected(f"Unknown scope: {scope_key}")

    membership = session.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == uuid.UUID(owner_id), TeamMembership.user_id == user_id
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotAuthorized("You are not a member of that channel")

    if spec.required_role == ChannelRole.CHANNEL_ADMIN and membership.role != ChannelRole.CHANNEL_ADMIN:
        raise NotAuthorized(f"{spec.label} requires a channel admin")


# --- approve / reject ------------------------------------------------------


def approve_action(session: Session, action: Action, user_id: uuid.UUID) -> Action:
    spec = get_spec(action.action_type)
    _assert_authorized(session, spec, action.scope_key, user_id)

    if action.status in _TERMINAL:
        raise ActionRejected("That action is already finished")
    if action.status == ActionStatus.EXECUTING:
        raise ActionRejected("That action is already running")

    action.status = ActionStatus.APPROVED
    action.approved_by_user_id = user_id
    action.approved_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(action)
    return action


def reject_action(session: Session, action: Action, user_id: uuid.UUID) -> Action:
    spec = get_spec(action.action_type)
    _assert_authorized(session, spec, action.scope_key, user_id)

    if action.status in _TERMINAL:
        return action
    action.status = ActionStatus.REJECTED
    action.approved_by_user_id = user_id
    action.approved_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(action)
    return action


# --- execute + verify ------------------------------------------------------


def execute_action(session: Session, action: Action, user_id: uuid.UUID) -> Action:
    """Run an approved action exactly once, then confirm it worked.

    The EXECUTING transition is committed before anything is attempted, so a
    concurrent second call finds a non-APPROVED status and refuses. Combined
    with the unique idempotency key at proposal time, a double-clicked
    Confirm cannot produce two calendar events.
    """
    spec = get_spec(action.action_type)
    _assert_authorized(session, spec, action.scope_key, user_id)

    if action.status in _TERMINAL:
        # Already done. Returning it unchanged is the correct answer to
        # "run this again" for an idempotent surface.
        return action
    if action.status != ActionStatus.APPROVED:
        raise ActionRejected("That action has not been approved")

    action.status = ActionStatus.EXECUTING
    session.commit()

    try:
        result = spec.execute(session, action)
    except ActionRejected as exc:
        return _finish(session, action, ActionStatus.FAILED, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - provider failures are expected
        logger.warning("action_execution_failed", action_id=str(action.id), error=str(exc)[:300])
        return _finish(session, action, ActionStatus.FAILED, error=_safe_error(exc))

    # Execution is not completion.
    try:
        verified, how = spec.verify(session, action, result) if spec.verify else (True, "No verification defined")
    except Exception as exc:  # noqa: BLE001
        logger.warning("action_verification_error", action_id=str(action.id), error=str(exc)[:300])
        verified, how = False, "Verification could not be completed"

    if verified:
        return _finish(session, action, ActionStatus.SUCCEEDED, result=result, verification=how)

    # Ran, but unconfirmed. UNKNOWN rather than FAILED, so nobody is told to
    # do it again when it may already exist.
    return _finish(session, action, ActionStatus.UNKNOWN, result=result, verification=how)


def _finish(
    session: Session,
    action: Action,
    status: ActionStatus,
    *,
    result: dict | None = None,
    error: str | None = None,
    verification: str | None = None,
) -> Action:
    action.status = status
    action.result = result or {}
    action.error = error
    action.verification = verification
    action.executed_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(action)
    logger.info(
        "action_finished",
        action_id=str(action.id), type=action.action_type, status=status.value,
        verified=bool(verification and status == ActionStatus.SUCCEEDED),
    )
    return action


def _safe_error(exc: Exception) -> str:
    """Provider errors reach a screen, so they must not carry tokens, auth
    headers or full response bodies."""
    text = str(exc)
    for marker in ("Bearer ", "access_token", "client_secret", "Authorization"):
        if marker in text:
            return f"{type(exc).__name__}: the provider rejected the request"
    return f"{type(exc).__name__}: {text[:200]}"


# --- reading ---------------------------------------------------------------


def list_actions(session: Session, scope_key: str, *, pending_only: bool = False) -> list[Action]:
    query = select(Action).where(Action.scope_key == scope_key)
    if pending_only:
        query = query.where(Action.status.in_([ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL]))
    rows = list(session.execute(query).scalars())
    return sorted(rows, key=lambda a: a.created_at, reverse=True)


def audit_trail(session: Session, workspace_id: uuid.UUID, *, limit: int = 100) -> list[Action]:
    """What Sentinel actually changed. Ordered newest first, and carrying
    only what the record needs - the executors already reduced provider
    responses to ids, titles and links."""
    return list(session.execute(
        select(Action)
        .where(Action.workspace_id == workspace_id, Action.executed_at.isnot(None))
        .order_by(Action.executed_at.desc())
        .limit(limit)
    ).scalars())
