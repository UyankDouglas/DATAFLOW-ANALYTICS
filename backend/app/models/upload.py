import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey, utcnow


class Upload(UUIDPrimaryKey, Base):
    """Arquivo original recebido. O conteúdo vive no armazenamento de objetos."""

    __tablename__ = "uploads"
    __table_args__ = (CheckConstraint("file_format IN ('csv', 'xlsx')", name="format_valid"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    file_format: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    # Resultado da inspeção no recebimento: encoding, delimitador, linhas estimadas...
    detection: Mapped[dict[str, Any]] = mapped_column(default=dict)
    upload_ms: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
