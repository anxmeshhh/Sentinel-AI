"""GitHub's view of connection health - a thin alias over the generic layer.

There is no GitHub-specific health logic. A repository is ready, syncing,
erroring, paused or revoked for the same reasons any monitored resource is, so
the derivation lives in `connection_state` and this module only re-exports it
under GitHub's vocabulary. It exists so GitHub call sites and tests can read in
repository terms; delete it and nothing but the names would change.

When the second provider lands, it imports `connection_state` directly rather
than growing its own copy of this file.
"""

from app.services.connection_state import ConnectionState, connection_state

# GitHub-facing names. Identical members and behaviour - the repository *is* the
# connection, so its state is the connection's state.
RepositoryState = ConnectionState
github_repository_state = connection_state

__all__ = ["RepositoryState", "github_repository_state"]
