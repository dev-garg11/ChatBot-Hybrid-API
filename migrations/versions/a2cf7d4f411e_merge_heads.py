"""merge heads

Revision ID: a2cf7d4f411e
Revises: 7307ca25663a, 76cde45436bb
Create Date: 2026-04-07 12:46:21.622276

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2cf7d4f411e'
down_revision: Union[str, Sequence[str], None] = ('7307ca25663a', '76cde45436bb')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
