"""commitment suggestions and commitment investigations

Revision ID: 9cf969a28a4a
Revises: d95566f286ff
Create Date: 2026-07-22 18:05:32.861796

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9cf969a28a4a'
down_revision: Union[str, None] = 'd95566f286ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('investigations', sa.Column('commitment_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_investigations_commitment_id'), 'investigations', ['commitment_id'], unique=False)
    op.create_unique_constraint('uq_investigation_commitment_scope', 'investigations', ['commitment_id', 'scope_key'])
    op.create_foreign_key(
        'fk_investigations_commitment_id', 'investigations', 'commitments', ['commitment_id'], ['id'], ondelete='CASCADE'
    )

    # Hand-added: autogenerate diffs tables and columns, not Enum *members*.
    # Without these the new values exist only in Python and every insert of
    # one fails at the database with a truncation error. Same footgun that
    # bit the shared-connection scope enum in Phase 2.
    op.execute(
        "ALTER TABLE commitments MODIFY source "
        "ENUM('MANUAL','TRACKED','EXTRACTED') NOT NULL"
    )
    op.execute(
        "ALTER TABLE commitments MODIFY status "
        "ENUM('SUGGESTED','PENDING','DUE_SOON','AT_RISK','OVERDUE','RESOLVED','DISMISSED') NOT NULL"
    )


def downgrade() -> None:
    # Rows using the new members must go before the members do, or the
    # narrowing ALTER silently coerces them to an empty string.
    op.execute("DELETE FROM commitments WHERE source = 'EXTRACTED' OR status = 'SUGGESTED'")
    op.execute("ALTER TABLE commitments MODIFY source ENUM('MANUAL','TRACKED') NOT NULL")
    op.execute(
        "ALTER TABLE commitments MODIFY status "
        "ENUM('PENDING','DUE_SOON','AT_RISK','OVERDUE','RESOLVED','DISMISSED') NOT NULL"
    )

    op.drop_constraint('fk_investigations_commitment_id', 'investigations', type_='foreignkey')
    op.drop_constraint('uq_investigation_commitment_scope', 'investigations', type_='unique')
    op.drop_index(op.f('ix_investigations_commitment_id'), table_name='investigations')
    op.drop_column('investigations', 'commitment_id')
