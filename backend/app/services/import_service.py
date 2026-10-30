"""Solicitação de importação: valida a configuração, congela-a no job e enfileira."""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models import (
    RUNNING_STATUSES,
    DatasetColumn,
    DatasetStatus,
    JobStatus,
    ProcessingJob,
)
from app.models.base import utcnow
from app.processing.types import RULES_VERSION, DataType, normalize_column_name
from app.repositories import datasets as repo
from app.schemas.dataset import ImportRequest
from app.services import audit
from app.services.preview_service import read_sample
from app.tasks.dispatch import enqueue_import

logger = logging.getLogger(__name__)


def _validate_columns(request: ImportRequest, header: list[str], column_count: int) -> None:
    columns = request.columns
    if len(columns) != column_count:
        raise ValidationFailed(
            f"O arquivo tem {column_count} colunas com as opções escolhidas, "
            f"mas {len(columns)} foram configuradas.",
            code="column_count_mismatch",
        )
    if sorted(c.position for c in columns) != list(range(column_count)):
        raise ValidationFailed("Cada coluna do arquivo deve ser configurada exatamente uma vez.")
    for column in columns:
        if header[column.position] != column.source_name:
            raise ValidationFailed(
                "A configuração não corresponde ao cabeçalho atual do arquivo. Recarregue a pré-visualização.",
                code="header_mismatch",
            )
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for column in columns:
        key = normalize_column_name(column.name).casefold()
        if key in seen:
            duplicates.append(column.name)
        seen[key] = column.name
    if duplicates:
        raise ValidationFailed(
            "Existem nomes de coluna duplicados. Renomeie-os antes de processar.",
            code="duplicate_column_names",
            details={"columns": duplicates},
        )


def start_import(
    db: Session,
    ctx: RequestContext,
    dataset_id: object,
    request: ImportRequest,
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
            if existing.dataset_id != dataset_id:
                raise Conflict("Chave de idempotência já utilizada em outra operação.")
            return existing

    dataset = repo.get_dataset(db, ctx.workspace_id, dataset_id, for_update=True)  # type: ignore[arg-type]
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
    upload = repo.latest_upload(db, dataset.id)
    if upload is None:
        raise NotFound("Nenhum arquivo enviado para este dataset.")

    options = request.parse_options
    if options.encoding == "utf-8" and not upload.detection.get("utf8_valid", True):
        raise ValidationFailed(
            "O arquivo não é UTF-8 válido. Selecione o encoding correto antes de processar.",
            code="encoding_not_confirmed",
        )
    analysis = read_sample(upload, options)
    _validate_columns(request, analysis.sample.header, analysis.sample.column_count)

    inferred = {i.position: i for i in analysis.inferences}
    ambiguous = [
        c.name
        for c in request.columns
        if c.data_type in (DataType.DATE, DataType.DATETIME)
        and c.format in inferred[c.position].ambiguous_formats
    ]
    if ambiguous and not request.confirm_ambiguous_formats:
        raise ValidationFailed(
            "Confirme o formato das colunas de data ambíguas antes de processar.",
            code="ambiguous_formats_not_confirmed",
            details={"columns": ambiguous},
        )

    # Mapeamento salvo e reutilizável no dataset.
    dataset.parse_options = options.model_dump()
    dataset.columns.clear()
    db.flush()
    for column in sorted(request.columns, key=lambda c: c.position):
        dataset.columns.append(
            DatasetColumn(
                position=column.position,
                source_name=column.source_name,
                name=column.name,
                data_type=column.data_type,
                inferred_type=inferred[column.position].inferred_type,
                format=column.format,
            )
        )

    now = utcnow()
    job = ProcessingJob(
        workspace_id=ctx.workspace_id,
        dataset_id=dataset.id,
        upload_id=upload.id,
        created_by_id=ctx.user.id,
        kind="import",
        status=JobStatus.QUEUED,
        idempotency_key=idempotency_key,
        config={
            "parse_options": options.model_dump(),
            "columns": [c.model_dump(mode="json") for c in request.columns],
            "expected_header": analysis.sample.header if options.has_header else None,
            "confirm_ambiguous_formats": request.confirm_ambiguous_formats,
            "transformations": [],  # motor de transformações chega na Fase 2
        },
        rules_version=RULES_VERSION,
        max_attempts=settings.job_max_attempts,
        bytes_total=upload.size_bytes,
        queued_at=now,
    )
    db.add(job)
    dataset.status = (
        DatasetStatus.PROCESSING if dataset.current_version_id is None else dataset.status
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(
            "Já existe um processamento em andamento para este dataset.", code="job_in_progress"
        ) from exc
    audit.record(
        db,
        "import.requested",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="job",
        entity_id=job.id,
        details={"dataset_id": str(dataset.id), "upload_id": str(upload.id)},
        ip=ctx.ip,
    )
    db.commit()

    if enqueue_import(job.id):
        job.enqueued_at = utcnow()
        job.celery_task_id = str(job.id)
        db.commit()
    return job
