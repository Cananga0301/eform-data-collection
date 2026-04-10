"""add_source_record_ids_to_verification_log

Revision ID: a3f82e1c9b04
Revises: d17c55fb0d71
Create Date: 2026-04-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3f82e1c9b04'
down_revision: Union[str, None] = 'd17c55fb0d71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('verification_log', sa.Column('source_record_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('verification_log', 'source_record_ids')
