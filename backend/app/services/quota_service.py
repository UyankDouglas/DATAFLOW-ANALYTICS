"""Cota de armazenamento por workspace.

A instalação de produção roda num único host: sem cota, uma conta enchia o disco que o MinIO
divide com o PostgreSQL e o Redis. O uso soma os originais não expurgados, os Parquet das versões
e as exportações prontas, e é conferido na entrada (upload e cópia de aba), antes de gravar.
Versões geradas por transformação e exportações entram na conta, mas não são bloqueadas.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import MB, get_settings
from app.core.errors import PayloadTooLarge
from app.models import DatasetVersion, ExportJob, ExportStatus, Upload

GB = 1024 * MB


def storage_usage(db: Session, workspace_id: uuid.UUID) -> int:
    uploads = db.scalar(
        select(func.coalesce(func.sum(Upload.size_bytes), 0)).where(
            Upload.workspace_id == workspace_id, Upload.purged_at.is_(None)
        )
    )
    versions = db.scalar(
        select(func.coalesce(func.sum(DatasetVersion.size_bytes), 0)).where(
            DatasetVersion.workspace_id == workspace_id
        )
    )
    exports = db.scalar(
        select(func.coalesce(func.sum(ExportJob.size_bytes), 0)).where(
            ExportJob.workspace_id == workspace_id, ExportJob.status == ExportStatus.SUCCEEDED
        )
    )
    return int(uploads or 0) + int(versions or 0) + int(exports or 0)


def quota_bytes() -> int | None:
    quota = get_settings().workspace_storage_quota_mb
    return quota * MB if quota > 0 else None


def check_quota(db: Session, workspace_id: uuid.UUID, incoming_bytes: int) -> None:
    quota = quota_bytes()
    if quota is None:
        return
    used = storage_usage(db, workspace_id)
    if used + incoming_bytes > quota:
        raise PayloadTooLarge(
            f"O workspace atingiu o limite de armazenamento ({used / GB:.1f} de {quota / GB:.1f} GB). "
            "Exclua datasets ou versões que não usa mais, ou ative a retenção dos originais nas "
            "configurações.",
            code="storage_quota_exceeded",
            details={"used_bytes": used, "quota_bytes": quota, "incoming_bytes": incoming_bytes},
        )
