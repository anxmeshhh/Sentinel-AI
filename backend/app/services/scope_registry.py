"""The scope registry - the single place that answers "which scopes are live in
this workspace?" so the Intelligence Core can run once per scope.

Every active scope is either one person's personal scope (they own connections)
or one channel's scope (a team that may be authorized for shared connections).
The Core runs the identical engines against each; this registry is the only new
moving part scope-awareness requires. It mirrors the enumeration the proactive
engine already does (services/proactive.py::refresh_proactive_for_workspace) -
one seam, reused, rather than each engine re-deciding what a scope is.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.scope import Scope
from app.models.connection import Connection
from app.models.team import Team
from app.services.investigation import channel_scope, personal_scope


def active_scopes(session: Session, workspace_id: uuid.UUID) -> list[Scope]:
    """Every scope the Intelligence Core should run for in one workspace:
    each connection-owning user's personal scope, then each channel's scope."""
    scopes: list[Scope] = []

    owner_ids = session.execute(
        select(Connection.user_id).where(Connection.workspace_id == workspace_id).distinct()
    ).scalars().all()
    for user_id in owner_ids:
        if user_id is not None:
            scopes.append(personal_scope(session, workspace_id, user_id))

    team_ids = session.execute(
        select(Team.id).where(Team.workspace_id == workspace_id)
    ).scalars().all()
    for team_id in team_ids:
        scopes.append(channel_scope(session, team_id))

    return scopes
