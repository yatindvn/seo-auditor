"""accessibility results

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('accessibility_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('critical', sa.Integer(), nullable=False),
    sa.Column('serious', sa.Integer(), nullable=False),
    sa.Column('moderate', sa.Integer(), nullable=False),
    sa.Column('minor', sa.Integer(), nullable=False),
    sa.Column('violations_json', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_accessibility_results_audit_id'), 'accessibility_results', ['audit_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_accessibility_results_audit_id'), table_name='accessibility_results')
    op.drop_table('accessibility_results')
