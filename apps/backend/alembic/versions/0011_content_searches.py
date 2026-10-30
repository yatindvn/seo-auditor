"""content searches

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-31 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('content_searches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('topic', sa.String(length=80), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('language', sa.String(length=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.Column('result_json', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_searches_topic'), 'content_searches', ['topic'], unique=False)
    op.create_index(op.f('ix_content_searches_created_at'), 'content_searches', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_content_searches_created_at'), table_name='content_searches')
    op.drop_index(op.f('ix_content_searches_topic'), table_name='content_searches')
    op.drop_table('content_searches')
