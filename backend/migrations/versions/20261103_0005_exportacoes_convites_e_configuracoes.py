"""exportações, convites, configurações do workspace e retenção de originais

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03

Mudança aditiva: duas tabelas novas (export_jobs, workspace_invitations) e duas colunas novas
(workspaces.settings com padrão '{}', uploads.purged_at nula). Nenhum dado existente é alterado.
O downgrade descarta essas tabelas e colunas: perde o histórico de exportações, os convites
pendentes e as configurações gravadas (os arquivos exportados no armazenamento não são apagados
por ele).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table('workspace_invitations',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('invited_by_id', sa.Uuid(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_by_id', sa.Uuid(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role IN ('admin', 'analyst', 'viewer')", name=op.f('ck_workspace_invitations_role_valid')),
    sa.ForeignKeyConstraint(['accepted_by_id'], ['users.id'], name=op.f('fk_workspace_invitations_accepted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['invited_by_id'], ['users.id'], name=op.f('fk_workspace_invitations_invited_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workspace_invitations_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspace_invitations')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_workspace_invitations_token_hash'))
    )
    op.create_index(op.f('ix_workspace_invitations_workspace_id'), 'workspace_invitations', ['workspace_id'], unique=False)
    op.create_table('export_jobs',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('format', sa.String(length=10), nullable=False),
    sa.Column('params', JSON, nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('file_name', sa.String(length=160), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('row_count', sa.BigInteger(), nullable=True),
    sa.Column('error_code', sa.String(length=60), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('enqueued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('download_count', sa.Integer(), nullable=False),
    sa.Column('last_downloaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("format IN ('csv', 'xlsx')", name=op.f('ck_export_jobs_format_valid')),
    sa.CheckConstraint("kind IN ('rows', 'report')", name=op.f('ck_export_jobs_kind_valid')),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'expired')", name=op.f('ck_export_jobs_status_valid')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_export_jobs_created_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], name=op.f('fk_export_jobs_dataset_id_datasets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['dataset_versions.id'], name=op.f('fk_export_jobs_version_id_dataset_versions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_export_jobs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_export_jobs'))
    )
    op.create_index(op.f('ix_export_jobs_dataset_id'), 'export_jobs', ['dataset_id'], unique=False)
    op.create_index('ix_export_jobs_status_expires', 'export_jobs', ['status', 'expires_at'], unique=False)
    op.create_index(op.f('ix_export_jobs_version_id'), 'export_jobs', ['version_id'], unique=False)
    op.create_index('ix_export_jobs_workspace_created', 'export_jobs', ['workspace_id', 'created_at'], unique=False)
    op.add_column('uploads', sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('workspaces', sa.Column('settings', JSON, server_default=sa.text("'{}'"), nullable=False))


def downgrade() -> None:
    op.drop_column('workspaces', 'settings')
    op.drop_column('uploads', 'purged_at')
    op.drop_index('ix_export_jobs_workspace_created', table_name='export_jobs')
    op.drop_index(op.f('ix_export_jobs_version_id'), table_name='export_jobs')
    op.drop_index('ix_export_jobs_status_expires', table_name='export_jobs')
    op.drop_index(op.f('ix_export_jobs_dataset_id'), table_name='export_jobs')
    op.drop_table('export_jobs')
    op.drop_index(op.f('ix_workspace_invitations_workspace_id'), table_name='workspace_invitations')
    op.drop_table('workspace_invitations')
