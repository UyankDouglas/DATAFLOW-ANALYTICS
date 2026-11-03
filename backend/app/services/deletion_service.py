"""Exclusão controlada de datasets e versões.

Antes de excluir, a API calcula o impacto (versões, arquivos, jobs, dashboards e exportações) e
recusa o que estiver em uso: processamento ou exportação em andamento, versão fixada por um
dashboard, única versão do dataset. Excluir um dataset exige digitar o nome dele. O banco é
limpo numa transação, em ordem explícita (jobs e uploads são referenciados com RESTRICT); os
arquivos no armazenamento são apagados depois do commit. Se essa limpeza falhar, sobram objetos
órfãos, sem nenhuma referência ou rota que os alcance, e o erro fica no log.
"""

import logging
import uuid
from pathlib import Path

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.config import get_settings
from app.core.errors import Conflict, ValidationFailed
from app.models import (
    ACTIVE_EXPORT_STATUSES,
    RUNNING_STATUSES,
    Dashboard,
    Dataset,
    DatasetColumn,
    DatasetVersion,
    ExportJob,
    JobStatus,
    ProcessingJob,
    QualityReport,
    TransformationSet,
    Upload,
)
from app.repositories import datasets as repo
from app.schemas.deletion import DashboardRef, DatasetImpact, VersionImpact
from app.services import audit, storage

logger = logging.getLogger(__name__)

ACTIVE_JOBS = (JobStatus.QUEUED, *RUNNING_STATUSES)


def _count(db: Session, model: type, *conditions: ColumnElement[bool]) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


def _active_jobs(db: Session, dataset_id: uuid.UUID) -> int:
    return _count(
        db,
        ProcessingJob,
        ProcessingJob.dataset_id == dataset_id,
        ProcessingJob.status.in_(ACTIVE_JOBS),
    )


def _active_exports(db: Session, *conditions: ColumnElement[bool]) -> int:
    return _count(db, ExportJob, ExportJob.status.in_(ACTIVE_EXPORT_STATUSES), *conditions)


def _dashboards(db: Session, *conditions: ColumnElement[bool]) -> list[DashboardRef]:
    rows = db.execute(
        select(Dashboard.id, Dashboard.name).where(*conditions).order_by(Dashboard.name)
    ).all()
    return [DashboardRef(id=i, name=n) for i, n in rows]


# ---------------------------------------------------------------- dataset


def dataset_impact(db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID) -> DatasetImpact:
    dataset = repo.get_dataset(db, workspace_id, dataset_id)
    version_bytes = db.scalar(
        select(func.coalesce(func.sum(DatasetVersion.size_bytes), 0)).where(
            DatasetVersion.dataset_id == dataset.id
        )
    )
    upload_bytes = db.scalar(
        select(func.coalesce(func.sum(Upload.size_bytes), 0)).where(
            Upload.dataset_id == dataset.id, Upload.purged_at.is_(None)
        )
    )
    blocked = None
    if _active_jobs(db, dataset.id):
        blocked = "Há um processamento em andamento neste dataset. Aguarde ou cancele-o."
    elif _active_exports(db, ExportJob.dataset_id == dataset.id):
        blocked = "Há uma exportação em andamento deste dataset. Aguarde ela terminar."
    return DatasetImpact(
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        versions=_count(db, DatasetVersion, DatasetVersion.dataset_id == dataset.id),
        uploads=_count(db, Upload, Upload.dataset_id == dataset.id),
        jobs=_count(db, ProcessingJob, ProcessingJob.dataset_id == dataset.id),
        exports=_count(db, ExportJob, ExportJob.dataset_id == dataset.id),
        stored_bytes=int(version_bytes or 0) + int(upload_bytes or 0),
        dashboards=_dashboards(db, Dashboard.dataset_id == dataset.id),
        blocked_reason=blocked,
    )


def _evict_cache(names: list[str]) -> None:
    cache = get_settings().cache_dir
    for name in names:
        (cache / name).unlink(missing_ok=True)


def delete_dataset(
    db: Session, ctx: RequestContext, dataset_id: uuid.UUID, confirm_name: str
) -> DatasetImpact:
    impact = dataset_impact(db, ctx.workspace_id, dataset_id)
    if impact.blocked_reason:
        raise Conflict(impact.blocked_reason, code="dataset_in_use")
    if confirm_name.strip() != impact.dataset_name:
        raise ValidationFailed(
            "Digite o nome do dataset exatamente como aparece para confirmar.",
            code="confirmation_mismatch",
        )
    version_ids = list(
        db.scalars(select(DatasetVersion.id).where(DatasetVersion.dataset_id == dataset_id))
    )
    uploads = db.execute(
        select(Upload.id, Upload.storage_key, Upload.purged_at).where(
            Upload.dataset_id == dataset_id
        )
    ).all()
    export_keys = [
        k
        for k in db.scalars(select(ExportJob.storage_key).where(ExportJob.dataset_id == dataset_id))
        if k
    ]
    # Ordem explícita: quem referencia com RESTRICT sai antes do referenciado.
    db.execute(delete(ExportJob).where(ExportJob.dataset_id == dataset_id))
    db.execute(delete(Dashboard).where(Dashboard.dataset_id == dataset_id))
    db.execute(update(Dataset).where(Dataset.id == dataset_id).values(current_version_id=None))
    db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.dataset_id == dataset_id)
        .values(result_version_id=None, source_version_id=None)
    )
    db.execute(
        update(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .values(parent_version_id=None)
    )
    db.execute(delete(QualityReport).where(QualityReport.dataset_id == dataset_id))
    db.execute(delete(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id))
    db.execute(delete(ProcessingJob).where(ProcessingJob.dataset_id == dataset_id))
    db.execute(delete(Upload).where(Upload.dataset_id == dataset_id))
    db.execute(delete(TransformationSet).where(TransformationSet.dataset_id == dataset_id))
    db.execute(delete(DatasetColumn).where(DatasetColumn.dataset_id == dataset_id))
    db.execute(delete(Dataset).where(Dataset.id == dataset_id))
    audit.record(
        db,
        "dataset.deleted",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dataset",
        entity_id=dataset_id,
        details=impact.model_dump(
            mode="json", include={"versions", "uploads", "jobs", "exports", "stored_bytes"}
        )
        | {"dashboards": len(impact.dashboards)},
        ip=ctx.ip,
    )
    db.commit()
    _cleanup(
        prefixes=[storage.dataset_prefix(ctx.workspace_id, dataset_id)],
        keys=[key for _, key, purged in uploads if purged is None] + export_keys,
        what={"dataset_id": str(dataset_id)},
    )
    _evict_cache(
        [f"v-{v}.parquet" for v in version_ids]
        + [f"r-{v}.parquet" for v in version_ids]
        + [f"u-{u}.xlsx" for u, _, _ in uploads]
    )
    return impact


def _cleanup(prefixes: list[str], keys: list[str], what: dict[str, str]) -> None:
    try:
        for prefix in prefixes:
            storage.delete_prefix(prefix)
        for key in keys:
            storage.delete_object(key)
    except storage.StorageError:
        logger.exception("storage_cleanup_failed", extra=what)


# ---------------------------------------------------------------- versão


def version_impact(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, version_id: uuid.UUID
) -> VersionImpact:
    dataset = repo.get_dataset(db, workspace_id, dataset_id)
    version = repo.get_version(db, workspace_id, dataset.id, version_id)
    others = list(
        db.scalars(
            select(DatasetVersion.version_number)
            .where(DatasetVersion.dataset_id == dataset.id, DatasetVersion.id != version.id)
            .order_by(DatasetVersion.version_number.desc())
        )
    )
    is_current = dataset.current_version_id == version.id
    pinned = _dashboards(db, Dashboard.version_id == version.id)
    blocked = None
    if not others:
        blocked = "É a única versão do dataset. Para apagar tudo, exclua o dataset."
    elif pinned:
        names = ", ".join(d.name for d in pinned)
        blocked = f"Versão fixada pelos dashboards: {names}. Mude a versão deles antes."
    elif _count(
        db,
        ProcessingJob,
        ProcessingJob.status.in_(ACTIVE_JOBS),
        or_(ProcessingJob.source_version_id == version.id, ProcessingJob.dataset_id == dataset.id),
    ):
        blocked = "Há um processamento em andamento neste dataset. Aguarde ou cancele-o."
    elif _active_exports(db, ExportJob.version_id == version.id):
        blocked = "Há uma exportação em andamento desta versão. Aguarde ela terminar."
    return VersionImpact(
        version_id=version.id,
        version_number=version.version_number,
        is_current=is_current,
        next_current_number=others[0] if is_current and others else None,
        derived_versions=_count(db, DatasetVersion, DatasetVersion.parent_version_id == version.id),
        exports=_count(db, ExportJob, ExportJob.version_id == version.id),
        stored_bytes=version.size_bytes,
        pinned_by=pinned,
        blocked_reason=blocked,
    )


def delete_version(
    db: Session, ctx: RequestContext, dataset_id: uuid.UUID, version_id: uuid.UUID
) -> VersionImpact:
    impact = version_impact(db, ctx.workspace_id, dataset_id, version_id)
    if impact.blocked_reason:
        raise Conflict(impact.blocked_reason, code="version_in_use")
    version = repo.get_version(db, ctx.workspace_id, dataset_id, version_id)
    prefix = str(Path(version.storage_key).parent).replace("\\", "/") + "/"
    export_keys = [
        k
        for k in db.scalars(select(ExportJob.storage_key).where(ExportJob.version_id == version.id))
        if k
    ]
    if impact.is_current:
        replacement = db.scalar(
            select(DatasetVersion.id).where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetVersion.version_number == impact.next_current_number,
            )
        )
        db.execute(
            update(Dataset).where(Dataset.id == dataset_id).values(current_version_id=replacement)
        )
    db.execute(delete(ExportJob).where(ExportJob.version_id == version.id))
    db.execute(
        update(DatasetVersion)
        .where(DatasetVersion.parent_version_id == version.id)
        .values(parent_version_id=None)
    )
    db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.result_version_id == version.id)
        .values(result_version_id=None)
    )
    db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.source_version_id == version.id)
        .values(source_version_id=None)
    )
    db.execute(delete(QualityReport).where(QualityReport.version_id == version.id))
    db.execute(delete(DatasetVersion).where(DatasetVersion.id == version.id))
    audit.record(
        db,
        "dataset.version_deleted",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dataset_version",
        entity_id=version.id,
        details={
            "dataset_id": str(dataset_id),
            "version_number": impact.version_number,
            "new_current_number": impact.next_current_number,
            "exports": impact.exports,
        },
        ip=ctx.ip,
    )
    db.commit()
    _cleanup(prefixes=[prefix], keys=export_keys, what={"version_id": str(version_id)})
    _evict_cache([f"v-{version_id}.parquet", f"r-{version_id}.parquet"])
    return impact
