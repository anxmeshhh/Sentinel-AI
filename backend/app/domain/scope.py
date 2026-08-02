"""Scope - the universal parameter of the Intelligence Core.

A Scope is *whose intelligence this is*: the set of connections a run may read,
plus a stable key. Personal and Workspace intelligence are the SAME engines run
with a different Scope - never two systems. This is the one seam that keeps
"one Sentinel, different ways of working" true, and the one place the
Individual -> never -> Collective privacy boundary is enforced: an engine only
ever sees ``scope.connection_ids``, so a channel scope (which never contains a
personal connection) structurally cannot see personal data.

Kept intentionally small and dependency-free so every engine can take it as a
parameter without importing service code. The constructors that populate it
from the database (``personal_scope`` / ``channel_scope``) live in
services/investigation.py, which re-exports this class for backward
compatibility.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field


class ScopeType(str, enum.Enum):
    PERSONAL = "personal"  # one person's own connections
    CHANNEL = "channel"  # the connections a workspace channel is authorized for


@dataclass
class Scope:
    """The connection set an engine may read, decided up front.

    Only ``key`` is required, so the lightweight ``Scope(key=...)`` construction
    used by a few callers that need nothing but the key keeps working. The rich
    fields (``connection_ids``, ``workspace_id``, ``owner_id``) are populated by
    ``personal_scope`` / ``channel_scope`` for anything that actually reads data.
    """

    key: str  # "personal:{user_id}" | "channel:{team_id}"
    connection_ids: set[uuid.UUID] = field(default_factory=set)
    workspace_id: uuid.UUID | None = None
    # The subject the scope belongs to: a user_id (personal) or a team_id (channel).
    owner_id: uuid.UUID | None = None

    @property
    def type(self) -> ScopeType:
        """Derived from the key - the single source of truth for the key format,
        so a scope's type can never disagree with its key."""
        return ScopeType.PERSONAL if self.key.startswith("personal:") else ScopeType.CHANNEL

    @property
    def is_personal(self) -> bool:
        return self.type is ScopeType.PERSONAL
