"""dashboards persistidos e seus widgets

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03

Mudança aditiva: duas tabelas novas. Nenhum dado existente é alterado. A versão fixada de um
dashboard referencia dataset_versions sem ON DELETE: enquanto um dashboard apontar para uma
versão, ela não pode ser excluída (a exclusão controlada de versões chega na Fase 5).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table('dashboards',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('filters', JSON, nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=True),
    sa.Column('updated_by_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_dashboards_created_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], name=op.f('fk_dashboards_dataset_id_datasets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], name=op.f('fk_dashboards_updated_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['version_id'], ['dataset_versions.id'], name=op.f('fk_dashboards_version_id_dataset_versions')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_dashboards_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dashboards')),
    sa.UniqueConstraint('workspace_id', 'name', name=op.f('uq_dashboards_workspace_id_name'))
    )
    op.create_index(op.f('ix_dashboards_dataset_id'), 'dashboards', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_dashboards_workspace_id'), 'dashboards', ['workspace_id'], unique=False)
    op.create_table('dashboard_widgets',
    sa.Column('dashboard_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('chart_type', sa.String(length=20), nullable=False),
    sa.Column('size', sa.String(length=10), nullable=False),
    sa.Column('config', JSON, nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("chart_type IN ('kpi', 'line', 'bar', 'bar_horizontal', 'area', 'pie', 'donut', 'table')", name=op.f('ck_dashboard_widgets_chart_type_valid')),
    sa.CheckConstraint("size IN ('small', 'medium', 'large')", name=op.f('ck_dashboard_widgets_size_valid')),
    sa.ForeignKeyConstraint(['dashboard_id'], ['dashboards.id'], name=op.f('fk_dashboard_widgets_dashboard_id_dashboards'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dashboard_widgets')),
    sa.UniqueConstraint('dashboard_id', 'position', name=op.f('uq_dashboard_widgets_dashboard_id_position'))
    )
    op.create_index(op.f('ix_dashboard_widgets_dashboard_id'), 'dashboard_widgets', ['dashboard_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_dashboard_widgets_dashboard_id'), table_name='dashboard_widgets')
    op.drop_table('dashboard_widgets')
    op.drop_index(op.f('ix_dashboards_workspace_id'), table_name='dashboards')
    op.drop_index(op.f('ix_dashboards_dataset_id'), table_name='dashboards')
    op.drop_table('dashboards')
