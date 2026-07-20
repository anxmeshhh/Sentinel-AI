"""add persona onboarding and demo workspace

Revision ID: 4dbd69f7d4bd
Revises: 6d420e904249
Create Date: 2026-07-20 06:18:11.870685

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4dbd69f7d4bd'
down_revision: Union[str, None] = '6d420e904249'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# MySQL stores an ENUM's allowed values in the column definition, and
# alembic's autogenerate does NOT detect a new *value* added to an existing
# Python enum - it only sees new columns. Adding DRIVE_FILE to SignalType
# therefore needs this explicit MODIFY, or every insert of the new type
# fails with a data-truncation error at runtime. Written out in full
# because MySQL replaces the whole value list, it doesn't append.
_SIGNAL_TYPE_WITH_DRIVE = (
    "ENUM('PR','REVIEW_SUBMITTED','COMMIT','ISSUE','CALENDAR_EVENT','EMAIL','DRIVE_FILE') NOT NULL"
)
_SIGNAL_TYPE_WITHOUT_DRIVE = (
    "ENUM('PR','REVIEW_SUBMITTED','COMMIT','ISSUE','CALENDAR_EVENT','EMAIL') NOT NULL"
)


def upgrade() -> None:
    op.add_column('users', sa.Column('persona', sa.Enum('INDIVIDUAL', 'DEVELOPER', 'TEAM', 'BUSINESS', 'EXPLORER', name='user_persona'), nullable=True))
    op.add_column('users', sa.Column('onboarded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('workspaces', sa.Column('is_demo', sa.Boolean(), server_default='0', nullable=False))
    op.execute(f"ALTER TABLE signals MODIFY COLUMN type {_SIGNAL_TYPE_WITH_DRIVE}")


def downgrade() -> None:
    # Demo-only rows; dropping the type means dropping them first, or the
    # MODIFY would silently truncate them to an empty string.
    op.execute("DELETE FROM signals WHERE type = 'DRIVE_FILE'")
    op.execute(f"ALTER TABLE signals MODIFY COLUMN type {_SIGNAL_TYPE_WITHOUT_DRIVE}")
    op.drop_column('workspaces', 'is_demo')
    op.drop_column('users', 'onboarded_at')
    op.drop_column('users', 'persona')
