"""Política de retenção dos arquivos originais enviados.

Quando o workspace define `original_retention_days`, os originais mais antigos que isso são
apagados do armazenamento de objetos. As versões publicadas (Parquet) continuam: o dataset segue
consultável, transformável e exportável. Só não é mais possível reprocessar aquele arquivo do zero
nem abrir a pré-visualização dele. Nunca é apagado o original de um dataset sem versão publicada
nem o de um upload usado por um processamento em andamento.
"""

import logging
from datetime import timedelta

from sqlalchemy import exists, select

from app.core.db import session_scope
from app.models import RUNNING_STATUSES, Dataset, JobStatus, ProcessingJob, Upload, Workspace
from app.models.base import utcnow
from app.schemas.workspace import WorkspaceSettings
from app.services import audit, storage

logger = logging.getLogger(__name__)

PURGE_BATCH = 200


def apply_retention() -> dict[str, int]:
    stats = {"workspaces": 0, "purged": 0, "failed": 0}
    now = utcnow()
    with session_scope() as db:
        workspaces = db.execute(select(Workspace.id, Workspace.settings)).all()
    for workspace_id, raw in workspaces:
        days = WorkspaceSettings.model_validate(raw or {}).original_retention_days
        if days is None:
            continue
        stats["workspaces"] += 1
        cutoff = now - timedelta(days=days)
        active = exists().where(
            ProcessingJob.upload_id == Upload.id,
            ProcessingJob.status.in_([JobStatus.QUEUED, *RUNNING_STATUSES]),
        )
        with session_scope() as db:
            uploads = db.scalars(
                select(Upload)
                .join(Dataset, Dataset.id == Upload.dataset_id)
                .where(
                    Upload.workspace_id == workspace_id,
                    Upload.purged_at.is_(None),
                    Upload.created_at < cutoff,
                    Dataset.current_version_id.is_not(None),
                    ~active,
                )
                .limit(PURGE_BATCH)
                .with_for_update(skip_locked=True)
            ).all()
            for upload in uploads:
                try:
                    storage.delete_object(upload.storage_key)
                except storage.StorageError:
                    stats["failed"] += 1
                    continue
                upload.purged_at = now
                audit.record(
                    db,
                    "retention.original_purged",
                    workspace_id=workspace_id,
                    entity_type="upload",
                    entity_id=upload.id,
                    details={
                        "dataset_id": str(upload.dataset_id),
                        "size_bytes": upload.size_bytes,
                        "retention_days": days,
                    },
                )
                stats["purged"] += 1
    if stats["purged"] or stats["failed"]:
        logger.info("retention_applied", extra=stats)
    return stats
