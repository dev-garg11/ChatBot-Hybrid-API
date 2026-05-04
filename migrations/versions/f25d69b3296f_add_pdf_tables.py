"""add pdf tables

Revision ID: f25d69b3296f
Revises: 11f98994a229
Create Date: 2026-03-25 12:04:30.950130

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = 'f25d69b3296f'
down_revision = '11f98994a229'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pdf_questions table create karo
    op.create_table('pdf_questions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('question_text', sa.Text(), nullable=True),
        sa.Column('question_vector', Vector(768), nullable=True),
        sa.Column('file_id', sa.Integer(), nullable=True),
        sa.Column('chunk_index', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # pdf_answers table create karo
    op.create_table('pdf_answers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=True),
        sa.Column('answer_text', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['question_id'], ['pdf_questions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('pdf_answers')
    op.drop_table('pdf_questions')