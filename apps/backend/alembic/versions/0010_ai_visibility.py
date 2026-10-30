"""ai visibility

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-31 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('ai_schedule', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('last_ai_run_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('ai_prompts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_prompts_project_id'), 'ai_prompts', ['project_id'], unique=False)

    op.create_table('ai_brand_terms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('owner', sa.String(length=255), nullable=False),
    sa.Column('term', sa.String(length=100), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'owner', 'term', name='uq_ai_brand_terms_owner_term')
    )
    op.create_index(op.f('ix_ai_brand_terms_project_id'), 'ai_brand_terms', ['project_id'], unique=False)

    op.create_table('ai_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('trigger', sa.String(length=16), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.Column('calls', sa.Integer(), nullable=False),
    sa.Column('errors', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_runs_project_id'), 'ai_runs', ['project_id'], unique=False)

    with op.batch_alter_table('ai_visibility_runs') as batch_op:
        batch_op.add_column(sa.Column('run_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('prompt_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('model', sa.String(length=64), server_default='', nullable=False))
        batch_op.add_column(sa.Column('answer', sa.Text(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('mentioned', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('position', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('brands_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('cited', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('citations_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('error', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('dry_run', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.create_index(batch_op.f('ix_ai_visibility_runs_run_id'), ['run_id'], unique=False)
        batch_op.create_foreign_key('fk_ai_visibility_runs_run_id', 'ai_runs', ['run_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('ai_visibility_runs') as batch_op:
        batch_op.drop_constraint('fk_ai_visibility_runs_run_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_ai_visibility_runs_run_id'))
        for column in ('dry_run', 'error', 'citations_json', 'cited', 'brands_json', 'position', 'mentioned',
                       'answer', 'model', 'prompt_id', 'run_id'):
            batch_op.drop_column(column)
    for table in ('ai_runs', 'ai_brand_terms', 'ai_prompts'):
        op.drop_index(op.f(f'ix_{table}_project_id'), table_name=table)
        op.drop_table(table)
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('last_ai_run_at')
        batch_op.drop_column('ai_schedule')
