"""backlinks

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('backlink_schedule', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('last_backlink_refresh_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('backlink_snapshots') as batch_op:
        batch_op.add_column(sa.Column('authority', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('backlinks', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('referring_domains', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('broken_backlinks', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('source', sa.String(length=16), server_default='snapshot', nullable=False))
        batch_op.add_column(sa.Column('period', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('dry_run', sa.Boolean(), server_default=sa.false(), nullable=False))

    op.create_table('backlink_ref_domains',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('backlinks', sa.Integer(), nullable=False),
    sa.Column('first_seen', sa.String(length=40), nullable=True),
    sa.ForeignKeyConstraint(['snapshot_id'], ['backlink_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_backlink_ref_domains_snapshot_id'), 'backlink_ref_domains', ['snapshot_id'], unique=False)

    op.create_table('backlink_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('url_from', sa.Text(), nullable=False),
    sa.Column('url_to', sa.Text(), nullable=False),
    sa.Column('anchor', sa.Text(), nullable=False),
    sa.Column('domain_from_rank', sa.Integer(), nullable=True),
    sa.Column('dofollow', sa.Boolean(), nullable=False),
    sa.Column('first_seen', sa.String(length=40), nullable=True),
    sa.Column('last_seen', sa.String(length=40), nullable=True),
    sa.Column('target_status', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['snapshot_id'], ['backlink_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_backlink_links_snapshot_id'), 'backlink_links', ['snapshot_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_backlink_links_snapshot_id'), table_name='backlink_links')
    op.drop_table('backlink_links')
    op.drop_index(op.f('ix_backlink_ref_domains_snapshot_id'), table_name='backlink_ref_domains')
    op.drop_table('backlink_ref_domains')
    with op.batch_alter_table('backlink_snapshots') as batch_op:
        for column in ('dry_run', 'period', 'source', 'broken_backlinks', 'referring_domains', 'backlinks', 'authority'):
            batch_op.drop_column(column)
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('last_backlink_refresh_at')
        batch_op.drop_column('backlink_schedule')
