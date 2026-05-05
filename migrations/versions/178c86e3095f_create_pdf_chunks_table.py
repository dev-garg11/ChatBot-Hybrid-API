"""create pdf_chunks table (clean)"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = '178c86e3095f'
down_revision: Union[str, Sequence[str], None] = 'a2cf7d4f411e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create pdf_chunks table safely"""

    op.create_table(
        'pdf_chunks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(384)),
        sa.Column('image_paths', sa.Text()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('status', sa.Boolean(), default=True)
    )


def downgrade() -> None:
    """Drop pdf_chunks table"""

    op.drop_table('pdf_chunks')