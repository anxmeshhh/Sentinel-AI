"""Phase 2r: "How do you work?" onboarding.

Persona is *configuration of one platform*, never a fork - it only changes
which connections are suggested first and which surfaces get emphasis.
Every capability stays reachable for every persona, and a user can change
persona at any time without losing anything.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import Persona, User
from app.schemas.onboarding import DemoWorkspaceOut, OnboardingStateOut, OnboardingUpdate
from app.services.demo_data import create_demo_workspace

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

# Suggested first connections per persona. Deliberately not a hard filter -
# the Connections page always shows everything; this only orders what we
# put in front of someone on day one. Kept profession-agnostic in shape so
# adding CRM/education/design categories later is a data change, not a
# redesign.
PERSONA_SUGGESTIONS: dict[Persona, list[str]] = {
    Persona.INDIVIDUAL: ["gmail", "google_calendar", "google_drive"],
    Persona.DEVELOPER: ["github", "gmail", "google_calendar", "google_drive"],
    Persona.TEAM: ["gmail", "google_calendar", "google_drive", "github"],
    Persona.BUSINESS: ["gmail", "google_calendar", "google_drive"],
    Persona.EXPLORER: [],  # nothing to connect - the demo workspace is pre-seeded
}

PERSONAS_WITH_CHANNELS = {Persona.TEAM, Persona.BUSINESS, Persona.EXPLORER}


def _state(user: User) -> OnboardingStateOut:
    return OnboardingStateOut(
        persona=user.persona.value if user.persona else None,
        onboarded_at=user.onboarded_at,
        suggested_providers=PERSONA_SUGGESTIONS.get(user.persona, []) if user.persona else [],
        show_channels=user.persona in PERSONAS_WITH_CHANNELS if user.persona else False,
    )


@router.get("", response_model=OnboardingStateOut)
def get_onboarding_state(user: User = Depends(get_current_user)) -> OnboardingStateOut:
    return _state(user)


@router.post("", response_model=OnboardingStateOut)
def set_persona(
    payload: OnboardingUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OnboardingStateOut:
    try:
        persona = Persona(payload.persona)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown persona: {payload.persona}")

    user.persona = persona
    user.onboarded_at = user.onboarded_at or datetime.now(timezone.utc)
    session.commit()
    session.refresh(user)
    return _state(user)


@router.post("/demo", response_model=DemoWorkspaceOut)
def enter_demo(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DemoWorkspaceOut:
    """Create (or re-seed) this user's Explore workspace and return it, so
    the frontend can switch straight into it. Re-seeding on every entry is
    intentional: timestamps are relative, so the demo always reads as
    happening today rather than whenever it was first created."""
    workspace, count = create_demo_workspace(session, user)
    return DemoWorkspaceOut(workspace_id=workspace.id, name=workspace.name, signals_seeded=count)
