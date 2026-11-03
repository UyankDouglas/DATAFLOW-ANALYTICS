"""transformações, linhagem de versões e mapeamento com obrigatoriedade

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03

Mudanças aditivas: novas tabelas e colunas anuláveis ou com valor padrão. Nenhum dado
existente é alterado; versões da Fase 1 ficam com filtered_count = 0 e duplicate_count nulo
(deduplicação não avaliada), que é exatamente o que elas representam.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')
OPERATIONS = (
    "'trim', 'normalize_text', 'change_case', 'convert_type', 'standardize_dates', "
    "'fix_numbers', 'handle_nulls', 'remove_empty_rows', 'filter_rows', 'rename_columns', "
    "'derived_column', 'deduplicate'"
)


def _is_sqlite() -> bool:
    # O alvo é PostgreSQL; o SQLite (só verificação local) não suporta ALTER de restrições.
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    op.create_table('transformation_sets',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=True),
    sa.Column('updated_by_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_transformation_sets_created_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], name=op.f('fk_transformation_sets_dataset_id_datasets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], name=op.f('fk_transformation_sets_updated_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_transformation_sets_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transformation_sets')),
    sa.UniqueConstraint('dataset_id', 'name', name=op.f('uq_transformation_sets_dataset_id_name'))
    )
    op.create_index(op.f('ix_transformation_sets_dataset_id'), 'transformation_sets', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_transformation_sets_workspace_id'), 'transformation_sets', ['workspace_id'], unique=False)
    op.create_table('transformation_rules',
    sa.Column('set_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('operation', sa.String(length=40), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('params', JSON, nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(f"operation IN ({OPERATIONS})", name=op.f('ck_transformation_rules_operation_valid')),
    sa.ForeignKeyConstraint(['set_id'], ['transformation_sets.id'], name=op.f('fk_transformation_rules_set_id_transformation_sets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transformation_rules')),
    sa.UniqueConstraint('set_id', 'position', name=op.f('uq_transformation_rules_set_id_position'))
    )
    op.create_index(op.f('ix_transformation_rules_set_id'), 'transformation_rules', ['set_id'], unique=False)

    op.add_column('dataset_columns', sa.Column('scale', sa.Integer(), nullable=True))
    op.add_column('dataset_columns', sa.Column('required', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('dataset_columns', sa.Column('fill_value', sa.String(length=200), nullable=True))

    op.add_column('dataset_versions', sa.Column('parent_version_id', sa.Uuid(), nullable=True))
    op.add_column('dataset_versions', sa.Column('transformation_set_id', sa.Uuid(), nullable=True))
    op.add_column('dataset_versions', sa.Column('filtered_count', sa.BigInteger(), server_default=sa.text('0'), nullable=False))
    op.add_column('dataset_versions', sa.Column('duplicate_count', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_dataset_versions_parent_version_id'), 'dataset_versions', ['parent_version_id'], unique=False)

    op.add_column('processing_jobs', sa.Column('source_version_id', sa.Uuid(), nullable=True))
    op.add_column('processing_jobs', sa.Column('transformation_set_id', sa.Uuid(), nullable=True))
    op.add_column('processing_jobs', sa.Column('rows_filtered', sa.BigInteger(), nullable=True))
    op.add_column('processing_jobs', sa.Column('rows_duplicates', sa.BigInteger(), nullable=True))

    if _is_sqlite():
        return
    op.create_foreign_key(op.f('fk_dataset_versions_parent_version_id_dataset_versions'), 'dataset_versions', 'dataset_versions', ['parent_version_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_dataset_versions_transformation_set_id_transformation_sets'), 'dataset_versions', 'transformation_sets', ['transformation_set_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_processing_jobs_source_version_id_dataset_versions', 'processing_jobs', 'dataset_versions', ['source_version_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_processing_jobs_transformation_set_id_transformation_sets'), 'processing_jobs', 'transformation_sets', ['transformation_set_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint(
        op.f('ck_dataset_versions_exclusions_non_negative'), 'dataset_versions',
        'filtered_count >= 0 AND (duplicate_count IS NULL OR duplicate_count >= 0)',
    )
    op.drop_constraint(op.f('ck_processing_jobs_kind_valid'), 'processing_jobs', type_='check')
    op.create_check_constraint(op.f('ck_processing_jobs_kind_valid'), 'processing_jobs', "kind IN ('import', 'transform')")


def downgrade() -> None:
    if not _is_sqlite():
        # Jobs de transformação não existem no esquema anterior: remova-os antes de voltar.
        op.drop_constraint(op.f('ck_processing_jobs_kind_valid'), 'processing_jobs', type_='check')
        op.create_check_constraint(op.f('ck_processing_jobs_kind_valid'), 'processing_jobs', "kind IN ('import')")
        op.drop_constraint(op.f('ck_dataset_versions_exclusions_non_negative'), 'dataset_versions', type_='check')
        op.drop_constraint(op.f('fk_processing_jobs_transformation_set_id_transformation_sets'), 'processing_jobs', type_='foreignkey')
        op.drop_constraint('fk_processing_jobs_source_version_id_dataset_versions', 'processing_jobs', type_='foreignkey')
        op.drop_constraint(op.f('fk_dataset_versions_transformation_set_id_transformation_sets'), 'dataset_versions', type_='foreignkey')
        op.drop_constraint(op.f('fk_dataset_versions_parent_version_id_dataset_versions'), 'dataset_versions', type_='foreignkey')
    op.drop_column('processing_jobs', 'rows_duplicates')
    op.drop_column('processing_jobs', 'rows_filtered')
    op.drop_column('processing_jobs', 'transformation_set_id')
    op.drop_column('processing_jobs', 'source_version_id')
    op.drop_index(op.f('ix_dataset_versions_parent_version_id'), table_name='dataset_versions')
    op.drop_column('dataset_versions', 'duplicate_count')
    op.drop_column('dataset_versions', 'filtered_count')
    op.drop_column('dataset_versions', 'transformation_set_id')
    op.drop_column('dataset_versions', 'parent_version_id')
    op.drop_column('dataset_columns', 'fill_value')
    op.drop_column('dataset_columns', 'required')
    op.drop_column('dataset_columns', 'scale')
    op.drop_index(op.f('ix_transformation_rules_set_id'), table_name='transformation_rules')
    op.drop_table('transformation_rules')
    op.drop_index(op.f('ix_transformation_sets_workspace_id'), table_name='transformation_sets')
    op.drop_index(op.f('ix_transformation_sets_dataset_id'), table_name='transformation_sets')
    op.drop_table('transformation_sets')
