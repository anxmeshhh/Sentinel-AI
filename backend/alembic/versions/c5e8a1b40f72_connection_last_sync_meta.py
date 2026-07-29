"""connection: add last_sync_meta

Phase 2 (Slack ingestion) monitoring: the last ingestion run's metrics -
{ok, signals, messages_scanned, duration_ms, at, error} - kept on the
connection so "is this sync healthy, and how much did it do" is answerable
without a separate table. Generic (every provider stamps it), NULL for rows
that have not synced since it was added.

Revision ID: c5e8a1b40f72
Revises: b3d7e6f21a09
Create Date: 2026-07-29 12:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5e8a1b40f72'
down_revision: Union[str, None] = 'b3d7e6f21a09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("last_sync_meta", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("connections", "last_sync_meta")
