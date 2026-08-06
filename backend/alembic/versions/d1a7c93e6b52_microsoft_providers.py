"""connection provider enum: add Microsoft 365 Sprint 1 services

Hand-written for the usual reason: autogenerate diffs tables/columns, not Enum
members, so these exist only in Python until the DB enum is widened here -
without it, inserting a Microsoft connection fails with a truncation error.
Additive; existing providers and their rows are untouched.

Revision ID: d1a7c93e6b52
Revises: c9e1f6b3d270
Create Date: 2026-08-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d1a7c93e6b52"
down_revision: Union[str, None] = "c9e1f6b3d270"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "'GITHUB','GOOGLE_CALENDAR','GMAIL','GOOGLE_DRIVE','SLACK'"
_NEW = _OLD + ",'MICROSOFT_OUTLOOK_MAIL','MICROSOFT_OUTLOOK_CALENDAR'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE connections MODIFY provider ENUM({_NEW}) NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM connections WHERE provider IN ('MICROSOFT_OUTLOOK_MAIL','MICROSOFT_OUTLOOK_CALENDAR')")
    op.execute(f"ALTER TABLE connections MODIFY provider ENUM({_OLD}) NOT NULL")
