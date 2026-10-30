"""search console

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def _stats(table):
    return [sa.Column('clicks', sa.Float(), nullable=False), sa.Column('impressions', sa.Float(), nullable=False),
            sa.Column('ctr', sa.Float(), nullable=False), sa.Column('position', sa.Float(), nullable=False)]


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('gsc_property', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('last_gsc_sync_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('gsc_daily',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    *_stats('gsc_daily'),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'date', name='uq_gsc_daily_project_date')
    )
    op.create_index(op.f('ix_gsc_daily_project_id'), 'gsc_daily', ['project_id'], unique=False)

    for table, key in (('gsc_pages', 'url'), ('gsc_queries', 'query')):
        op.create_table(table,
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column(key, sa.Text(), nullable=False),
        *_stats(table),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dry_run', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f(f'ix_{table}_project_id'), table, ['project_id'], unique=False)

    op.create_table('gsc_inspections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('verdict', sa.String(length=16), nullable=True),
    sa.Column('coverage_state', sa.Text(), nullable=True),
    sa.Column('indexing_state', sa.String(length=64), nullable=True),
    sa.Column('robots_state', sa.String(length=32), nullable=True),
    sa.Column('fetch_state', sa.String(length=64), nullable=True),
    sa.Column('google_canonical', sa.Text(), nullable=True),
    sa.Column('user_canonical', sa.Text(), nullable=True),
    sa.Column('last_crawl', sa.String(length=40), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_gsc_inspections_audit_id'), 'gsc_inspections', ['audit_id'], unique=False)


def downgrade() -> None:
    for table in ('gsc_inspections', 'gsc_queries', 'gsc_pages', 'gsc_daily'):
        op.drop_index(op.f(f'ix_{table}_{"audit_id" if table == "gsc_inspections" else "project_id"}'), table_name=table)
        op.drop_table(table)
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('last_gsc_sync_at')
        batch_op.drop_column('gsc_property')
