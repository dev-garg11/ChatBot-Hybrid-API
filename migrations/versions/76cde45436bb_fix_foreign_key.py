"""fix foreign key

Revision ID: 76cde45436bb
Revises: 71cc913719ed
Create Date: 2026-03-17 15:44:29.578756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '76cde45436bb'
down_revision: Union[str, Sequence[str], None] = '71cc913719ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
