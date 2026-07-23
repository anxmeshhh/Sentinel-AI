"""The health of one monitored GitHub repository, as a single honest state.

Every state here is derived from something already recorded on the connection
row - a timestamp, a flag - so the answer is auditable and never a guess. The
distinctions matter operationally: "paused" is a choice, "revoked" needs the
user to reconnect, and "error" (tried and never succeeded) is a different
problem from "syncing" (trying for the first time), even though a naive read
of `last_synced_at` alone would blur them.

Two states the prompt asks for are deliberately absent from this stored
derivation:

- **CONNECTING** is the OAuth round trip, which holds no database row yet -
  there is nothing here to report it from.
- **OUTAGE** is "GitHub is unreachable right now", which is a property of a
  live request, not of the stored connection. The repo-list and sync routes
  return it as a 502 in the moment; inventing a stored OUTAGE would claim
  knowledge the row does not hold.

Both are real, and both belong to the request layer rather than here.
"""

import enum

from app.models.connection import Connection


class RepositoryState(str, enum.Enum):
    NEEDS_SETUP = "needs_setup"  # account connected, no repository chosen
    SYNCING = "syncing"  # first sync not finished yet
    READY = "ready"  # synced successfully at least once
    ERROR = "error"  # has attempted a sync but none has succeeded
    PAUSED = "paused"  # deliberately silenced; keeps its history
    TOKEN_REVOKED = "token_revoked"  # the grant is gone; reconnect needed


def github_repository_state(connection: Connection) -> RepositoryState:
    # Order matters: a paused connection is paused whatever else is true of it,
    # and a revoked one cannot be trusted regardless of past syncs.
    if connection.paused_at is not None:
        return RepositoryState.PAUSED
    if connection.revoked_at is not None:
        return RepositoryState.TOKEN_REVOKED
    if not connection.repo:
        return RepositoryState.NEEDS_SETUP
    if connection.last_synced_at is None:
        return RepositoryState.SYNCING
    # Tried at least once. If nothing ever succeeded, that is a failing
    # connection wearing a recent `last_synced_at` - the exact case
    # last_success_at exists to expose.
    if connection.last_success_at is None:
        return RepositoryState.ERROR
    return RepositoryState.READY
