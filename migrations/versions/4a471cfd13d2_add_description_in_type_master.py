"""add description in type_master
Revision ID: 4a471cfd13d2
Revises: 11f98994a229
Create Date: 2026-03-17 14:40:08.322323
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4a471cfd13d2'
down_revision: Union[str, Sequence[str], None] = '11f98994a229'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # faq_documents changes
    op.add_column('faq_documents', sa.Column('status', sa.Boolean(), nullable=True))
    op.drop_column('faq_documents', 'is_active')

    # pehle column add karo
    op.add_column(
        'faq_questions',
        sa.Column('type_master_id', sa.Integer(), nullable=True)
    )

    # phir foreign key lagao — 'id' ki jagah 'type_master_id'
    op.create_foreign_key(
        None,
        'faq_questions',
        'type_master',
        ['type_master_id'],
        ['type_master_id']  # FIXED
    )

    # type_master changes
    op.alter_column(
        'type_master',
        'type_name',
        existing_type=sa.VARCHAR(length=255),
        nullable=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # FK remove
    op.drop_constraint(None, 'faq_questions', type_='foreignkey')

    # column remove
    op.drop_column('faq_questions', 'type_master_id')

    # faq_documents rollback
    op.add_column('faq_documents', sa.Column('is_active', sa.Boolean(), nullable=True))
    op.drop_column('faq_documents', 'status')

    # type_master rollback
    op.alter_column(
        'type_master',
        'type_name',
        existing_type=sa.VARCHAR(length=255),
        nullable=True
    )