"""The health of one monitored resource, as a single honest state.

This lives in the generic layer on purpose. Every state here is derived from a
field that belongs to `Connection` itself - a timestamp, a flag - not from
anything a provider knows. A monitored Slack channel, Notion database or Jira
project is paused, revoked, syncing, erroring or ready for exactly the same
reasons a repository is, so the derivation is written once and every provider
reads it rather than re-deriving its own.

The distinctions matter operationally: "paused" is a choice, "revoked" needs
the user to reconnect, and "error" (tried and never succeeded) is a different
problem from "syncing" (trying for the first time), even though a naive read
of `last_synced_at` alone would blur them. `NEEDS_SETUP` - a connected account
with no resource yet chosen - reads `connection.repo`, which despite its name
is the generic resource identifier every provider stores (a repo, a mailbox
label, a channel id): an empty one means "connected, nothing chosen".

Two states some providers ask for are deliberately absent from this stored
derivation:

- **CONNECTING** is the OAuth round trip, which holds no database row yet -
  there is nothing here to report it from.
- **OUTAGE** is "the provider is unreachable right now", which is a property of
  a live request, not of the stored connection. Resource-list and sync routes
  return it as a 502 in the moment; inventing a stored OUTAGE would claim
  knowledge the row does not hold.

Both are real, and both belong to the request layer rather than here.
"""

import enum

from app.models.connection import Connection


class ConnectionState(str, enum.Enum):
    NEEDS_SETUP = "needs_setup"  # account connected, no resource chosen
    SYNCING = "syncing"  # first sync not finished yet
    READY = "ready"  # synced successfully at least once
    ERROR = "error"  # has attempted a sync but none has succeeded
    PAUSED = "paused"  # deliberately silenced; keeps its history
    TOKEN_REVOKED = "token_revoked"  # the grant is gone; reconnect needed


def connection_state(connection: Connection) -> ConnectionState:
    # Order matters: a paused connection is paused whatever else is true of it,
    # and a revoked one cannot be trusted regardless of past syncs.
    if connection.paused_at is not None:
        return ConnectionState.PAUSED
    if connection.revoked_at is not None:
        return ConnectionState.TOKEN_REVOKED
    if not connection.repo:
        return ConnectionState.NEEDS_SETUP
    if connection.last_synced_at is None:
        return ConnectionState.SYNCING
    # Tried at least once. If nothing ever succeeded, that is a failing
    # connection wearing a recent `last_synced_at` - the exact case
    # last_success_at exists to expose.
    if connection.last_success_at is None:
        return ConnectionState.ERROR
    return ConnectionState.READY
