"""custom rules

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('custom_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('message', sa.String(length=200), nullable=False),
    sa.Column('url_pattern', sa.String(length=200), nullable=True),
    sa.Column('check_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_custom_rules_project_id'), 'custom_rules', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_custom_rules_project_id'), table_name='custom_rules')
    op.drop_table('custom_rules')
