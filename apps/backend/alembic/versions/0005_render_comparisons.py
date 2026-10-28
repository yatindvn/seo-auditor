"""render comparisons

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('render_comparisons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('render_ms', sa.Float(), nullable=True),
    sa.Column('raw_word_count', sa.Integer(), nullable=True),
    sa.Column('rendered_word_count', sa.Integer(), nullable=True),
    sa.Column('changes_json', sa.JSON(), nullable=False),
    sa.Column('js_only_links_json', sa.JSON(), nullable=False),
    sa.Column('js_only_links_count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_render_comparisons_audit_id'), 'render_comparisons', ['audit_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_render_comparisons_audit_id'), table_name='render_comparisons')
    op.drop_table('render_comparisons')
