"""add document_id and image_paths

Revision ID: 7307ca25663a
Revises: f25d69b3296f
Create Date: 2026-04-02 10:03:17.457404

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy  
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7307ca25663a'
down_revision: Union[str, Sequence[str], None] = 'f25d69b3296f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Sirf yeh 3 cheezein karni hain
    
    # 1. pdf_questions mein document_id add karo
    op.add_column('pdf_questions', sa.Column('document_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'pdf_questions', 'faq_documents', ['document_id'], ['id'])
    
    # 2. pdf_questions mein created_at aur status add karo
    op.add_column('pdf_questions', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('pdf_questions', sa.Column('status', sa.Boolean(), nullable=True))
    
    # 3. pdf_answers mein image_paths, answer_vector, created_at, status add karo
    op.add_column('pdf_answers', sa.Column('answer_vector', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True))
    op.add_column('pdf_answers', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('pdf_answers', sa.Column('status', sa.Boolean(), nullable=True))
    op.add_column('pdf_answers', sa.Column('image_paths', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('pdf_answers', 'image_paths')
    op.drop_column('pdf_answers', 'status')
    op.drop_column('pdf_answers', 'created_at')
    op.drop_column('pdf_answers', 'answer_vector')
    op.drop_column('pdf_questions', 'status')
    op.drop_column('pdf_questions', 'created_at')
    op.drop_constraint(None, 'pdf_questions', type_='foreignkey')
    op.drop_column('pdf_questions', 'document_id')