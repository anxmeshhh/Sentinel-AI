"""What this Zoom account can actually do - asked of Zoom, not guessed.

The twin of microsoft_capabilities, and it exists for the same reason: two of
the things people most want from Zoom (cloud recordings, and who actually
attended) are **plan-gated**. A Basic/free account has neither. Reporting that as
an error teaches people the integration is broken; reporting it as a capability
teaches them something true about their account.

Detection is real, and layered from cheapest to most certain:

    GET /users/me            -> `type`: 1 Basic, 2 Licensed, 3 On-prem. This is
                                Zoom stating the plan outright.
    GET /users/me/recordings -> the honest test. A plan claim is a hint; whether
                                the endpoint actually answers is the fact. An
                                account can be Licensed with cloud recording
                                disabled by an admin, which `type` alone cannot
                                tell you.

Nothing here keys off an email domain or a hardcoded list. The probe is cached
against the account identity, so connecting a different account invalidates it.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass

import structlog

from app.integrations.zoom_client import ZoomClient, ZoomError, ZoomPlanError

logger = structlog.get_logger("sentinel.zoom_capabilities")

# Probing costs up to two API calls, and the answer only changes when the plan
# changes or a different account connects - both rare, both self-invalidating.
_CACHE_TTL_SECONDS = 900
_cache: dict[str, tuple[float, "ZoomAccount"]] = {}


class PlanType(str, enum.Enum):
    BASIC = "basic"  # free: meetings yes, cloud recording no, reports no
    LICENSED = "licensed"  # Pro and above
    ON_PREM = "on_prem"
    UNKNOWN = "unknown"


_PLAN_BY_CODE = {1: PlanType.BASIC, 2: PlanType.LICENSED, 3: PlanType.ON_PREM}


class CapabilityState(str, enum.Enum):
    """Three states, not two. `AVAILABLE`/`UNAVAILABLE` alone would force an
    honest "we could not tell" into one of the two confident answers."""

    AVAILABLE = "available"
    REQUIRES_PLAN = "requires_plan"  # the account's plan does not include it
    UNKNOWN = "unknown"  # could not determine; say so rather than guess


@dataclass(frozen=True)
class ZoomAccount:
    email: str
    display_name: str
    plan: PlanType
    timezone: str
    personal_meeting_url: str
    recordings: CapabilityState
    participants: CapabilityState

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "display_name": self.display_name,
            "plan": self.plan.value,
            "timezone": self.timezone,
            "personal_meeting_url": self.personal_meeting_url,
            "capabilities": {
                "meetings": {
                    # Never gated: scheduling is what every Zoom account has, and
                    # it is the capability the whole integration is built on.
                    "state": CapabilityState.AVAILABLE.value,
                    "label": "Meetings",
                    "detail": "Schedule, edit and cancel meetings from Sentinel.",
                },
                "recordings": {
                    "state": self.recordings.value,
                    "label": "Cloud recordings & transcripts",
                    "detail": _RECORDING_DETAIL[self.recordings],
                },
                "participants": {
                    "state": self.participants.value,
                    "label": "Attendance reports",
                    "detail": _PARTICIPANT_DETAIL[self.participants],
                },
            },
        }


_RECORDING_DETAIL = {
    CapabilityState.AVAILABLE: "Recordings and transcripts from this account are readable in Sentinel.",
    CapabilityState.REQUIRES_PLAN: (
        "Cloud recording is part of Zoom's paid plans. This account records locally only, "
        "and local recordings never reach Zoom's API - so Sentinel cannot see them."
    ),
    CapabilityState.UNKNOWN: "Sentinel could not check whether recordings are available on this account.",
}

_PARTICIPANT_DETAIL = {
    CapabilityState.AVAILABLE: "Sentinel can show who actually joined each past meeting.",
    CapabilityState.REQUIRES_PLAN: "Zoom restricts attendance reporting to paid plans.",
    CapabilityState.UNKNOWN: "Sentinel could not check whether attendance reporting is available.",
}


def describe_account(access_token: str, *, account_key: str) -> ZoomAccount:
    """Ask Zoom what this account is and what it can do. Never raises: a probe
    that fails yields UNKNOWN capabilities, because a diagnostic must not be
    able to break the page it is diagnosing."""
    cached = _cache.get(account_key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    email = display_name = timezone_name = personal_url = ""
    plan = PlanType.UNKNOWN
    try:
        with ZoomClient(access_token) as client:
            me = client.me()
            email = me["email"]
            display_name = me["display_name"]
            timezone_name = me["timezone"]
            personal_url = me["personal_meeting_url"]
            plan = _PLAN_BY_CODE.get(me["plan_type"], PlanType.UNKNOWN)

            recordings = _probe_recordings(client)
    except Exception as exc:  # noqa: BLE001 - a failed probe is UNKNOWN, never an error
        logger.info("zoom_capability_probe_failed", error=str(exc)[:200])
        recordings = CapabilityState.UNKNOWN

    # Attendance reporting is not probed with a live call: doing so needs a real
    # past-meeting uuid, which a brand-new account does not have, so a probe
    # would report REQUIRES_PLAN for an account that simply has no history yet.
    # The plan is the honest available evidence, and UNKNOWN when even that is.
    participants = {
        PlanType.BASIC: CapabilityState.REQUIRES_PLAN,
        PlanType.LICENSED: CapabilityState.AVAILABLE,
        PlanType.ON_PREM: CapabilityState.AVAILABLE,
        PlanType.UNKNOWN: CapabilityState.UNKNOWN,
    }[plan]

    account = ZoomAccount(
        email=email, display_name=display_name, plan=plan, timezone=timezone_name,
        personal_meeting_url=personal_url, recordings=recordings, participants=participants,
    )
    _cache[account_key] = (time.monotonic(), account)
    return account


def _probe_recordings(client: ZoomClient) -> CapabilityState:
    """The real test: does the endpoint answer?

    An empty list is AVAILABLE, not unavailable - "you have no recordings yet"
    and "your plan cannot record" are completely different things to tell someone.
    """
    try:
        client.recordings()
    except ZoomPlanError:
        return CapabilityState.REQUIRES_PLAN
    except ZoomError as exc:
        # A 403 here is Zoom refusing the scope rather than the plan; either way
        # Sentinel cannot read recordings, but it should not claim to know why.
        logger.info("zoom_recording_probe_failed", error=str(exc)[:200])
        return CapabilityState.UNKNOWN
    return CapabilityState.AVAILABLE


def clear_cache() -> None:
    _cache.clear()
