"""The gate an action must pass to run without a person present.

Nothing in Sentinel currently runs unattended. This is the check a future
scheduler or event-driven proposer would have to satisfy, built and tested
now so that turning one on is a policy decision rather than a redesign.

`autonomy_allows` returns a reason for every refusal, and the reasons are
surfaced rather than logged away - "why did Sentinel ask me instead of just
doing it?" should always have an answer.
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action import Action, ActionRisk, ActionStatus
from app.models.action_policy import ActionPolicy
from app.models.team import ChannelRole, TeamMembership
from app.services.action_registry import Reversibility, get_spec

logger = structlog.get_logger("sentinel.action_policy")


class PolicyDenied(Exception):
    pass


def autonomy_allows(session: Session, *, scope_key: str, action_type: str, risk: ActionRisk) -> tuple[bool, str]:
    """May this run unattended? Four independent conditions, all required.

    Deliberately redundant. A single flag deciding whether software acts on
    its own is one mistake away from it acting on its own, so the registry,
    the risk, the reversibility and an explicit human opt-in must all agree.
    """
    spec = get_spec(action_type)

    if not spec.autonomy_eligible:
        return False, f"{spec.label} is never run unattended"
    if risk is not ActionRisk.LOW:
        return False, "Only low-risk actions can run unattended"
    if spec.reversibility is not Reversibility.REVERSIBLE:
        # Compensatable is not good enough: undoing a calendar invite still
        # notifies everyone who received it.
        return False, "Only fully reversible actions can run unattended"

    policy = session.execute(
        select(ActionPolicy).where(
            ActionPolicy.scope_key == scope_key, ActionPolicy.action_type == action_type
        )
    ).scalar_one_or_none()
    if policy is None or not policy.enabled:
        return False, "Nobody has enabled this to run unattended in this context"

    used = _executed_today(session, scope_key, action_type)
    if used >= policy.daily_limit:
        return False, f"Daily limit reached ({used}/{policy.daily_limit})"

    return True, f"Enabled in this context, {used}/{policy.daily_limit} used today"


def _executed_today(session: Session, scope_key: str, action_type: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    return len(session.execute(
        select(Action.id).where(
            Action.scope_key == scope_key,
            Action.action_type == action_type,
            Action.executed_at.isnot(None),
            Action.executed_at >= since,
            Action.status.in_([ActionStatus.SUCCEEDED, ActionStatus.UNKNOWN]),
        )
    ).scalars().all())


def set_policy(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    scope_key: str,
    action_type: str,
    enabled: bool,
    user_id: uuid.UUID,
    daily_limit: int = 5,
) -> ActionPolicy:
    """Turn unattended execution on or off for one action in one scope.

    Refuses outright for anything the registry would never allow unattended,
    so an impossible policy cannot be stored and later look like consent.
    """
    spec = get_spec(action_type)
    if enabled and not spec.autonomy_eligible:
        raise PolicyDenied(f"{spec.label} can never run unattended")
    if enabled and spec.reversibility is not Reversibility.REVERSIBLE:
        raise PolicyDenied(f"{spec.label} is not fully reversible and cannot run unattended")

    _assert_may_set_policy(session, scope_key, user_id)

    policy = session.execute(
        select(ActionPolicy).where(
            ActionPolicy.scope_key == scope_key, ActionPolicy.action_type == action_type
        )
    ).scalar_one_or_none()
    if policy is None:
        policy = ActionPolicy(workspace_id=workspace_id, scope_key=scope_key, action_type=action_type)
        session.add(policy)

    policy.enabled = enabled
    policy.daily_limit = max(1, min(100, daily_limit))
    policy.enabled_by_user_id = user_id
    policy.enabled_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(policy)

    logger.info(
        "action_policy_set",
        scope=scope_key, action_type=action_type, enabled=enabled, by=str(user_id),
    )
    return policy


def _assert_may_set_policy(session: Session, scope_key: str, user_id: uuid.UUID) -> None:
    """The unit of consent matches the unit of consequence.

    Enabling something in your own context is your call. Enabling it in a
    channel affects everyone there, so it is a channel-admin decision.
    """
    kind, _, owner_id = scope_key.partition(":")
    if kind == "personal":
        if str(user_id) != owner_id:
            raise PolicyDenied("You can only set policy for your own context")
        return
    if kind != "channel":
        raise PolicyDenied(f"Unknown scope: {scope_key}")

    membership = session.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == uuid.UUID(owner_id), TeamMembership.user_id == user_id
        )
    ).scalar_one_or_none()
    if membership is None or membership.role != ChannelRole.CHANNEL_ADMIN:
        raise PolicyDenied("Only a channel admin can let Sentinel act unattended here")


def list_policies(session: Session, scope_key: str) -> list[ActionPolicy]:
    return list(session.execute(
        select(ActionPolicy).where(ActionPolicy.scope_key == scope_key)
    ).scalars())
