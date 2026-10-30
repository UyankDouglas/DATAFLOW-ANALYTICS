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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey, utcnow


class DatasetStatus(StrEnum):
    DRAFT = "draft"  # arquivo recebido, aguardando configuração
    PROCESSING = "processing"
    READY = "ready"  # possui ao menos uma versão publicada
    FAILED = "failed"  # último processamento falhou e não há versão publicada


class Dataset(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'processing', 'ready', 'failed')", name="status_valid"
        ),
        Index("ix_datasets_workspace_created", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=DatasetStatus.DRAFT)
    source_format: Mapped[str] = mapped_column(String(10))
    # Configuração de leitura salva e reutilizável (delimitador, encoding, nulos...).
    parse_options: Mapped[dict[str, Any]] = mapped_column(default=dict)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "dataset_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_datasets_current_version_id_dataset_versions",
        )
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    columns: Mapped[list["DatasetColumn"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetColumn.position",
    )


class DatasetColumn(UUIDPrimaryKey, Timestamps, Base):
    """Mapeamento de coluna salvo para o dataset (origem → nome/tipo de destino)."""

    __tablename__ = "dataset_columns"
    __table_args__ = (
        UniqueConstraint("dataset_id", "position"),
        UniqueConstraint("dataset_id", "name"),
        CheckConstraint(
            "data_type IN ('text', 'integer', 'decimal', 'date', 'datetime', 'boolean')",
            name="data_type_valid",
        ),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    source_name: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    data_type: Mapped[str] = mapped_column(String(20))
    inferred_type: Mapped[str | None] = mapped_column(String(20))
    format: Mapped[str | None] = mapped_column(String(40))

    dataset: Mapped[Dataset] = relationship(back_populates="columns")


class DatasetVersion(UUIDPrimaryKey, Base):
    """Versão publicada e imutável de um dataset (Parquet no armazenamento de objetos)."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_number"),
        CheckConstraint("status IN ('published')", name="status_valid"),
        CheckConstraint("row_count >= 0 AND rejected_count >= 0", name="counts_non_negative"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="published")
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="RESTRICT"), unique=True
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="RESTRICT"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    storage_key: Mapped[str] = mapped_column(String(512))
    rejected_storage_key: Mapped[str | None] = mapped_column(String(512))
    row_count: Mapped[int] = mapped_column(BigInteger)
    rejected_count: Mapped[int] = mapped_column(BigInteger)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    column_schema: Mapped[list[Any]] = mapped_column(default=list)
    transformations: Mapped[dict[str, Any]] = mapped_column(default=dict)
    reconciliation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    rules_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
