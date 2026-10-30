import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class JobStatus(StrEnum):
    """Códigos estáveis persistidos; os rótulos em português ficam na interface."""

    QUEUED = "queued"
    VALIDATING = "validating"
    PROCESSING = "processing"
    SAVING = "saving"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


RUNNING_STATUSES = (JobStatus.VALIDATING, JobStatus.PROCESSING, JobStatus.SAVING)
TERMINAL_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)

ACTIVE_JOB_FILTER = "status IN ('queued', 'validating', 'processing', 'saving')"


class ProcessingJob(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'validating', 'processing', 'saving', "
            "'succeeded', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("kind IN ('import')", name="kind_valid"),
        UniqueConstraint("workspace_id", "idempotency_key"),
        Index("ix_processing_jobs_workspace_created", "workspace_id", "created_at"),
        Index("ix_processing_jobs_status_heartbeat", "status", "heartbeat_at"),
        # No máximo um job ativo por dataset, garantido pelo banco.
        Index(
            "uq_processing_jobs_active_per_dataset",
            "dataset_id",
            unique=True,
            postgresql_where=text(ACTIVE_JOB_FILTER),
            sqlite_where=text(ACTIVE_JOB_FILTER),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="RESTRICT"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20), default="import")
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    celery_task_id: Mapped[str | None] = mapped_column(String(100))

    # Configuração congelada no momento da solicitação (reprodutibilidade).
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    rules_version: Mapped[str] = mapped_column(String(20))

    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    cancel_requested_at: Mapped[datetime | None]

    # Progresso medido sobre trabalho realmente concluído.
    bytes_total: Mapped[int | None] = mapped_column(BigInteger)
    bytes_processed: Mapped[int] = mapped_column(BigInteger, default=0)
    rows_processed: Mapped[int] = mapped_column(BigInteger, default=0)
    rows_total: Mapped[int | None] = mapped_column(BigInteger)  # exato só ao final
    rows_valid: Mapped[int | None] = mapped_column(BigInteger)
    rows_rejected: Mapped[int | None] = mapped_column(BigInteger)

    error_code: Mapped[str | None] = mapped_column(String(60))
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[Any]] = mapped_column(default=list)
    rejection_summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "dataset_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_processing_jobs_result_version_id_dataset_versions",
        )
    )

    queued_at: Mapped[datetime]
    enqueued_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
