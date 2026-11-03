import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class ExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"  # arquivo removido ao fim da validade (o registro fica no histórico)


EXPORT_KINDS = ("rows", "report")
EXPORT_FORMATS = ("csv", "xlsx")
ACTIVE_EXPORT_STATUSES = (ExportStatus.QUEUED, ExportStatus.RUNNING)


class ExportJob(UUIDPrimaryKey, Timestamps, Base):
    """Exportação gerada em segundo plano: registros tratados de uma versão (com os filtros do
    explorer) ou o resultado de um relatório. O arquivo é temporário e só sai pela API."""

    __tablename__ = "export_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'expired')",
            name="status_valid",
        ),
        CheckConstraint("kind IN ('rows', 'report')", name="kind_valid"),
        CheckConstraint("format IN ('csv', 'xlsx')", name="format_valid"),
        Index("ix_export_jobs_workspace_created", "workspace_id", "created_at"),
        Index("ix_export_jobs_status_expires", "status", "expires_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(10))
    format: Mapped[str] = mapped_column(String(10))
    # Consulta congelada no pedido: filtros, colunas e ordenação, ou a consulta do relatório.
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default=ExportStatus.QUEUED)
    # Nome sugerido no download, montado pelo backend (nunca o caminho no armazenamento).
    file_name: Mapped[str] = mapped_column(String(160))
    storage_key: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    enqueued_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    duration_ms: Mapped[int | None]
    download_count: Mapped[int] = mapped_column(default=0)
    last_downloaded_at: Mapped[datetime | None]
