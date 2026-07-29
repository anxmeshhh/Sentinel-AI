"""connection: add display_name

Phase 1 of Slack. A monitored Slack channel is a Connection whose `repo` holds
the channel *id* (stable across renames); its human name needs a home, so this
adds a generic nullable display_name. NULL for every existing row, so nothing
about GitHub/Google changes - full_name only prefers display_name when set.

Revision ID: b3d7e6f21a09
Revises: a1f4c8d90b21
Create Date: 2026-07-29 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d7e6f21a09'
down_revision: Union[str, None] = 'a1f4c8d90b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("display_name", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("connections", "display_name")
