"""Conjuntos de regras, prévia sobre amostra, análise de duplicidades e jobs de transformação.

As regras chegam como JSON validado por modelos Pydantic (operações de uma lista fechada) e são
conferidas contra o esquema da versão de origem antes de qualquer execução. Nada aqui interpreta
código, SQL ou expressões enviadas pelo usuário.
"""

import logging
import uuid
from typing import Any

import duckdb
import polars as pl
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analytics.cache import local_parquet
from app.analytics.query import duplicate_summary, to_json_value
from app.api.deps import RequestContext
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from app.models import (
    RUNNING_STATUSES,
    Dataset,
    DatasetVersion,
    JobKind,
    JobStatus,
    ProcessingJob,
    TransformationRule,
    TransformationSet,
    User,
)
from app.models.base import utcnow
from app.processing.convert import CATEGORY_FILTERED, CATEGORY_REJECTED
from app.processing.transforms import (
    DUPLICATE_REASON,
    RuleError,
    RulePlan,
    apply_rules,
    duplicate_exclusions,
    mark_duplicates,
    plan_rules,
    resolve_rules,
    rules_to_json,
)
from app.processing.types import RULES_VERSION, ColumnSpec
from app.repositories import datasets as repo
from app.schemas.transformation import (
    ColumnOut,
    DuplicateAnalysisRequest,
    DuplicateAnalysisResponse,
    DuplicateGroup,
    ExcludedRow,
    PreviewRow,
    TransformationSetIn,
    TransformationSetOut,
    TransformJobRequest,
    TransformPreviewRequest,
    TransformPreviewResponse,
)
from app.services import audit
from app.tasks.dispatch import enqueue_job

logger = logging.getLogger(__name__)

PREVIEW_VISIBLE_ROWS = 50


def version_schema(version: DatasetVersion) -> list[ColumnSpec]:
    return [ColumnSpec.model_validate(c) for c in version.column_schema]


def plan_or_422(rules: list[Any], schema: list[ColumnSpec]) -> RulePlan:
    try:
        return plan_rules(rules, schema)
    except RuleError as exc:
        raise ValidationFailed(
            str(exc),
            code="invalid_rule",
            details={"rule_index": exc.index, "message": exc.message},
        ) from exc


def _current_version(db: Session, dataset: Dataset) -> DatasetVersion:
    if dataset.current_version_id is None:
        raise ValidationFailed(
            "Processe o dataset antes de configurar transformações.", code="no_version"
        )
    version = db.get(DatasetVersion, dataset.current_version_id)
    assert version is not None
    return version


# ---------------------------------------------------------------- conjuntos de regras


def _stored_rules(tset: TransformationSet) -> list[dict[str, Any]]:
    return [{"operation": r.operation, "enabled": r.enabled, **r.params} for r in tset.rules]


def _rule_rows(rules: list[Any]) -> list[TransformationRule]:
    rows = []
    for position, data in enumerate(rules_to_json(rules)):
        operation, enabled = data.pop("operation"), data.pop("enabled")
        rows.append(
            TransformationRule(position=position, operation=operation, enabled=enabled, params=data)
        )
    return rows


def _set_out(db: Session, tset: TransformationSet) -> TransformationSetOut:
    ids = {i for i in (tset.created_by_id, tset.updated_by_id) if i}
    names = (
        dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())
        if ids
        else {}
    )
    return TransformationSetOut(
        id=tset.id,
        dataset_id=tset.dataset_id,
        name=tset.name,
        description=tset.description,
        revision=tset.revision,
        rules=_stored_rules(tset),
        created_by_name=names.get(tset.created_by_id) if tset.created_by_id else None,
        updated_by_name=names.get(tset.updated_by_id) if tset.updated_by_id else None,
        created_at=tset.created_at,
        updated_at=tset.updated_at,
    )


def _get_set(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, set_id: uuid.UUID
) -> TransformationSet:
    tset = db.scalar(
        select(TransformationSet).where(
            TransformationSet.id == set_id,
            TransformationSet.dataset_id == dataset_id,
            TransformationSet.workspace_id == workspace_id,
        )
    )
    if tset is None:
        raise NotFound("Conjunto de transformações não encontrado.")
    return tset


def _ensure_unique_name(
    db: Session, dataset_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    query = select(TransformationSet.id).where(
        TransformationSet.dataset_id == dataset_id, TransformationSet.name == name
    )
    if exclude is not None:
        query = query.where(TransformationSet.id != exclude)
    clash = db.scalar(query)
    if clash is not None:
        raise Conflict("Já existe um conjunto com este nome neste dataset.", code="duplicate_name")


def list_sets(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID
) -> list[TransformationSetOut]:
    repo.get_dataset(db, workspace_id, dataset_id)
    sets = db.scalars(
        select(TransformationSet)
        .where(
            TransformationSet.dataset_id == dataset_id,
            TransformationSet.workspace_id == workspace_id,
        )
        .order_by(TransformationSet.updated_at.desc())
    ).all()
    return [_set_out(db, s) for s in sets]


def get_set(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, set_id: uuid.UUID
) -> TransformationSetOut:
    repo.get_dataset(db, workspace_id, dataset_id)
    return _set_out(db, _get_set(db, workspace_id, dataset_id, set_id))


def _commit_set(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(
            "Já existe um conjunto com este nome neste dataset.", code="duplicate_name"
        ) from exc


def create_set(
    db: Session, ctx: RequestContext, dataset_id: uuid.UUID, data: TransformationSetIn
) -> TransformationSetOut:
    dataset = repo.get_dataset(db, ctx.workspace_id, dataset_id)
    plan_or_422(data.rules, version_schema(_current_version(db, dataset)))
    _ensure_unique_name(db, dataset.id, data.name)
    tset = TransformationSet(
        workspace_id=ctx.workspace_id,
        dataset_id=dataset.id,
        name=data.name,
        description=data.description,
        revision=1,
        created_by_id=ctx.user.id,
        updated_by_id=ctx.user.id,
    )
    tset.rules.extend(_rule_rows(data.rules))
    db.add(tset)
    db.flush()
    audit.record(
        db,
        "transformation_set.created",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="transformation_set",
        entity_id=tset.id,
        details={"dataset_id": str(dataset.id), "rules": len(data.rules)},
        ip=ctx.ip,
    )
    _commit_set(db)
    return _set_out(db, tset)


def update_set(
    db: Session,
    ctx: RequestContext,
    dataset_id: uuid.UUID,
    set_id: uuid.UUID,
    data: TransformationSetIn,
) -> TransformationSetOut:
    dataset = repo.get_dataset(db, ctx.workspace_id, dataset_id)
    tset = _get_set(db, ctx.workspace_id, dataset.id, set_id)
    plan_or_422(data.rules, version_schema(_current_version(db, dataset)))
    _ensure_unique_name(db, dataset.id, data.name, exclude=tset.id)
    tset.name = data.name
    tset.description = data.description
    # Versões já publicadas guardam a cópia das regras usadas; editar não as altera.
    tset.revision += 1
    tset.updated_by_id = ctx.user.id
    tset.updated_at = utcnow()
    tset.rules.clear()
    db.flush()
    tset.rules.extend(_rule_rows(data.rules))
    audit.record(
        db,
        "transformation_set.updated",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="transformation_set",
        entity_id=tset.id,
        details={"revision": tset.revision, "rules": len(data.rules)},
        ip=ctx.ip,
    )
    _commit_set(db)
    return _set_out(db, tset)


def delete_set(db: Session, ctx: RequestContext, dataset_id: uuid.UUID, set_id: uuid.UUID) -> None:
    repo.get_dataset(db, ctx.workspace_id, dataset_id)
    tset = _get_set(db, ctx.workspace_id, dataset_id, set_id)
    db.delete(tset)
    audit.record(
        db,
        "transformation_set.deleted",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="transformation_set",
        entity_id=set_id,
        details={"dataset_id": str(dataset_id)},
        ip=ctx.ip,
    )
    db.commit()


# ---------------------------------------------------------------- prévia e duplicidades


def _source_version(
    db: Session, workspace_id: uuid.UUID, dataset: Dataset, version_id: uuid.UUID | None
) -> DatasetVersion:
    if version_id is None:
        return _current_version(db, dataset)
    return repo.get_version(db, workspace_id, dataset.id, version_id)


def _columns_out(schema: list[ColumnSpec]) -> list[ColumnOut]:
    return [
        ColumnOut(name=c.name, data_type=c.data_type, format=c.format, scale=c.scale)
        for c in schema
    ]


def preview(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, request: TransformPreviewRequest
) -> TransformPreviewResponse:
    """Aplica as regras aos primeiros registros da versão, sem gravar nada."""
    settings = get_settings()
    dataset = repo.get_dataset(db, workspace_id, dataset_id)
    version = _source_version(db, workspace_id, dataset, request.source_version_id)
    schema = version_schema(version)
    plan = plan_or_422(request.rules, schema)
    path = local_parquet(f"v-{version.id}", version.storage_key, version.checksum_sha256)
    frame = pl.read_parquet(
        path,
        columns=["__df_row", *[c.name for c in schema]],
        n_rows=settings.transform_preview_rows,
    )

    batch = apply_rules(frame, plan)
    kept = batch.frame
    excluded = batch.excluded.with_columns(pl.lit(None, dtype=pl.Int64).alias("__df_duplicate_of"))
    reasons = dict(batch.reasons)
    duplicates: int | None = None
    if plan.dedup is not None:
        keep, removed = mark_duplicates(kept.lazy(), plan)
        kept = kept.filter(keep)
        duplicates = removed.height
        if duplicates:
            reasons[DUPLICATE_REASON] = duplicates
            excluded = pl.concat(
                [excluded, duplicate_exclusions(removed, plan).select(excluded.columns)],
                how="vertical_relaxed",
            )

    output = [c.name for c in plan.output]
    visible = kept.head(PREVIEW_VISIBLE_ROWS).select(["__df_row", *output])
    return TransformPreviewResponse(
        source_version_id=version.id,
        source_version_number=version.version_number,
        source_row_count=version.row_count,
        sample_size=frame.height,
        sample_is_complete=frame.height >= version.row_count,
        input_columns=_columns_out(schema),
        output_columns=_columns_out(plan.output),
        rows=[
            PreviewRow(row=row[0], values=[to_json_value(v) for v in row[1:]])
            for row in visible.iter_rows()
        ],
        excluded=[
            ExcludedRow(
                row=r["__df_row"],
                reason=r["__df_reason"],
                category=r["__df_category"],
                column=r["__df_column"],
                detail=r["__df_detail"],
                rule=r["__df_rule"],
                duplicate_of=r["__df_duplicate_of"],
            )
            for r in excluded.sort("__df_row").head(PREVIEW_VISIBLE_ROWS).iter_rows(named=True)
        ],
        counts={
            "received": frame.height,
            "valid": kept.height,
            "rejected": batch.categories.get(CATEGORY_REJECTED, 0),
            "filtered": batch.categories.get(CATEGORY_FILTERED, 0),
            "duplicates": duplicates,
        },
        reasons=reasons,
    )


def analyze_duplicates(
    db: Session,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    request: DuplicateAnalysisRequest,
) -> DuplicateAnalysisResponse:
    """Duplicidades na versão inteira (não só na amostra), sem alterar dados."""
    version = repo.get_version(db, workspace_id, dataset_id, version_id)
    names = [c["name"] for c in version.column_schema]
    keys = list(dict.fromkeys(request.columns)) or names
    unknown = [k for k in keys if k not in names]
    if unknown:
        raise ValidationFailed("Coluna desconhecida na análise.", details={"columns": unknown})
    path = local_parquet(f"v-{version.id}", version.storage_key, version.checksum_sha256)
    try:
        summary = duplicate_summary(path, keys)
    except duckdb.Error as exc:
        raise ServiceUnavailable("Não foi possível analisar as duplicidades agora.") from exc
    keep_first = request.keep == "first"
    return DuplicateAnalysisResponse(
        version_id=version.id,
        version_number=version.version_number,
        columns=keys,
        keep=request.keep,
        total_rows=summary.total_rows,
        distinct_keys=summary.distinct_keys,
        duplicate_rows=summary.duplicate_rows,
        rows_after=summary.total_rows - summary.duplicate_rows,
        groups_with_duplicates=summary.groups_with_duplicates,
        top_groups=[
            DuplicateGroup(
                key=g["key"],
                count=g["count"],
                kept_row=g["first_row"] if keep_first else g["last_row"],
                sample_rows=g["sample_rows"],
            )
            for g in summary.top_groups
        ],
    )


# ---------------------------------------------------------------- execução


def start_transform(
    db: Session,
    ctx: RequestContext,
    dataset_id: uuid.UUID,
    request: TransformJobRequest,
    idempotency_key: str | None,
) -> ProcessingJob:
    settings = get_settings()
    if idempotency_key:
        existing = db.scalar(
            select(ProcessingJob).where(
                ProcessingJob.workspace_id == ctx.workspace_id,
                ProcessingJob.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.dataset_id != dataset_id or existing.kind != JobKind.TRANSFORM:
                raise Conflict("Chave de idempotência já utilizada em outra operação.")
            return existing

    dataset = repo.get_dataset(db, ctx.workspace_id, dataset_id, for_update=True)
    active = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.dataset_id == dataset.id,
            ProcessingJob.status.in_([JobStatus.QUEUED, *RUNNING_STATUSES]),
        )
    )
    if active is not None:
        raise Conflict(
            "Já existe um processamento em andamento para este dataset.", code="job_in_progress"
        )
    version = repo.get_version(db, ctx.workspace_id, dataset.id, request.source_version_id)
    tset = _get_set(db, ctx.workspace_id, dataset.id, request.transformation_set_id)
    rules = resolve_rules(_stored_rules(tset))
    if not any(rule.enabled for rule in rules):
        raise ValidationFailed("Ative ao menos uma regra antes de aplicar.", code="no_active_rules")
    plan_or_422(rules, version_schema(version))

    job = ProcessingJob(
        workspace_id=ctx.workspace_id,
        dataset_id=dataset.id,
        upload_id=version.upload_id,
        created_by_id=ctx.user.id,
        kind=JobKind.TRANSFORM,
        source_version_id=version.id,
        transformation_set_id=tset.id,
        status=JobStatus.QUEUED,
        idempotency_key=idempotency_key,
        # Cópia congelada: editar o conjunto depois não muda o que este job aplica.
        config={
            "source_version_id": str(version.id),
            "source_version_number": version.version_number,
            "transformation_set": {
                "id": str(tset.id),
                "name": tset.name,
                "revision": tset.revision,
            },
            "rules": rules_to_json(rules),
        },
        rules_version=RULES_VERSION,
        max_attempts=settings.job_max_attempts,
        rows_total=version.row_count,
        queued_at=utcnow(),
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(
            "Já existe um processamento em andamento para este dataset.", code="job_in_progress"
        ) from exc
    audit.record(
        db,
        "transform.requested",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="job",
        entity_id=job.id,
        details={
            "dataset_id": str(dataset.id),
            "source_version_id": str(version.id),
            "transformation_set_id": str(tset.id),
            "revision": tset.revision,
        },
        ip=ctx.ip,
    )
    db.commit()

    if enqueue_job(job.id):
        job.enqueued_at = utcnow()
        job.celery_task_id = str(job.id)
        db.commit()
    return job
