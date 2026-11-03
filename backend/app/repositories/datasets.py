"""Consultas sempre filtradas pelo workspace do contexto (isolamento entre workspaces)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import Dataset, DatasetVersion, ProcessingJob, Upload


def get_dataset(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, *, for_update: bool = False
) -> Dataset:
    stmt = select(Dataset).where(Dataset.id == dataset_id, Dataset.workspace_id == workspace_id)
    if for_update:
        stmt = stmt.with_for_update()
    dataset = db.scalar(stmt)
    if dataset is None:
        # 404 tanto para inexistente quanto para alheio: não revela existência.
        raise NotFound("Dataset não encontrado.")
    return dataset


def latest_upload(db: Session, dataset_id: uuid.UUID) -> Upload | None:
    return db.scalar(
        select(Upload)
        .where(Upload.dataset_id == dataset_id)
        .order_by(Upload.created_at.desc())
        .limit(1)
    )


def get_version(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, version_id: uuid.UUID
) -> DatasetVersion:
    version = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == version_id,
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.workspace_id == workspace_id,
        )
    )
    if version is None:
        raise NotFound("Versão não encontrada.")
    return version


def resolve_version(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, version_id: uuid.UUID | None
) -> DatasetVersion:
    """Versão pedida ou, sem id, a versão atual do dataset."""
    dataset = get_dataset(db, workspace_id, dataset_id)
    target = version_id or dataset.current_version_id
    if target is None:
        raise NotFound("Este dataset ainda não possui versão processada.", code="no_version")
    return get_version(db, workspace_id, dataset_id, target)


def get_job(db: Session, workspace_id: uuid.UUID, job_id: uuid.UUID) -> ProcessingJob:
    job = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id, ProcessingJob.workspace_id == workspace_id
        )
    )
    if job is None:
        raise NotFound("Processamento não encontrado.")
    return job
