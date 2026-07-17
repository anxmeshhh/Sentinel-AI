"""Minimal identity model for Phase 1.5.

Deliberately no password/auth fields yet - Phase 1.5 only needs a real
`users` row to hang a Personal Workspace off of (IA.md's "every user always
has exactly one Personal Workspace"). Real login/session auth is Phase 2's
RBAC territory (PHASES.md); until then, `core/bootstrap.py` resolves to a
single default user, same pattern as the single default workspace in Phase 1.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class User(Base, UUIDPk, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
