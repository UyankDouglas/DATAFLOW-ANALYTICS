"""relatórios de qualidade por versão e grupos de inconsistências

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03

Mudança aditiva: duas tabelas novas. Nenhum dado existente é alterado; versões já publicadas
ficam sem relatório até que ele seja calculado (sob demanda ou ao reprocessar).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table('quality_reports',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('formula_version', sa.String(length=10), nullable=False),
    sa.Column('score', sa.Double(), nullable=True),
    sa.Column('metrics', JSON, nullable=False),
    sa.Column('computed_by_id', sa.Uuid(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('score IS NULL OR (score >= 0 AND score <= 100)', name=op.f('ck_quality_reports_score_range')),
    sa.ForeignKeyConstraint(['computed_by_id'], ['users.id'], name=op.f('fk_quality_reports_computed_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], name=op.f('fk_quality_reports_dataset_id_datasets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['dataset_versions.id'], name=op.f('fk_quality_reports_version_id_dataset_versions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_quality_reports_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quality_reports')),
    sa.UniqueConstraint('version_id', name=op.f('uq_quality_reports_version_id'))
    )
    op.create_index(op.f('ix_quality_reports_dataset_id'), 'quality_reports', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_quality_reports_workspace_id'), 'quality_reports', ['workspace_id'], unique=False)
    op.create_table('quality_issues',
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.String(length=60), nullable=False),
    sa.Column('column_name', sa.String(length=120), nullable=True),
    sa.Column('rule', sa.Integer(), nullable=True),
    sa.Column('count', sa.BigInteger(), nullable=False),
    sa.Column('example_row', sa.BigInteger(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("category IN ('rejeitado', 'filtrado', 'duplicado')", name=op.f('ck_quality_issues_category_valid')),
    sa.CheckConstraint('count > 0', name=op.f('ck_quality_issues_count_positive')),
    sa.ForeignKeyConstraint(['report_id'], ['quality_reports.id'], name=op.f('fk_quality_issues_report_id_quality_reports'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quality_issues'))
    )
    op.create_index(op.f('ix_quality_issues_report_id'), 'quality_issues', ['report_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_quality_issues_report_id'), table_name='quality_issues')
    op.drop_table('quality_issues')
    op.drop_index(op.f('ix_quality_reports_workspace_id'), table_name='quality_reports')
    op.drop_index(op.f('ix_quality_reports_dataset_id'), table_name='quality_reports')
    op.drop_table('quality_reports')
