"""add deadline attention type

Revision ID: 39dd0b640a85
Revises: 4dbd69f7d4bd
Create Date: 2026-07-20 06:34:20.342218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '39dd0b640a85'
down_revision: Union[str, None] = '4dbd69f7d4bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Hand-written for the same reason as the DRIVE_FILE migration: alembic's
# autogenerate detects new columns but not a new *value* on an existing
# enum, and MySQL stores the allowed values in the column definition. The
# full list is restated because MySQL replaces rather than appends.
_WITH_DEADLINE = (
    "ENUM('IMPORTANT_EMAIL','UPCOMING_MEETING','STALE_PR','FINDING','MANUAL','DEADLINE') NOT NULL"
)
_WITHOUT_DEADLINE = "ENUM('IMPORTANT_EMAIL','UPCOMING_MEETING','STALE_PR','FINDING','MANUAL') NOT NULL"


def upgrade() -> None:
    op.execute(f"ALTER TABLE attention_items MODIFY COLUMN type {_WITH_DEADLINE}")


def downgrade() -> None:
    # Drop the rows first: a MODIFY that removes a value in use would
    # silently truncate them to an empty string rather than fail loudly.
    op.execute("DELETE FROM attention_items WHERE type = 'DEADLINE'")
    op.execute(f"ALTER TABLE attention_items MODIFY COLUMN type {_WITHOUT_DEADLINE}")
