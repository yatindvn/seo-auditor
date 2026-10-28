"""web vitals

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25 23:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('web_vitals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('strategy', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('data_kind', sa.String(length=8), nullable=True),
    sa.Column('rating', sa.String(length=24), nullable=True),
    sa.Column('performance_score', sa.Float(), nullable=True),
    sa.Column('lcp_ms', sa.Float(), nullable=True),
    sa.Column('inp_ms', sa.Float(), nullable=True),
    sa.Column('cls', sa.Float(), nullable=True),
    sa.Column('fcp_ms', sa.Float(), nullable=True),
    sa.Column('ttfb_ms', sa.Float(), nullable=True),
    sa.Column('tbt_ms', sa.Float(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('measured_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_web_vitals_audit_id'), 'web_vitals', ['audit_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_web_vitals_audit_id'), table_name='web_vitals')
    op.drop_table('web_vitals')
