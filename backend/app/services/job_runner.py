"""Execução de jobs de importação no worker.

Garantias:
- Idempotência: o job só é executado após uma reivindicação condicional no PostgreSQL.
  Reentregas de jobs concluídos, cancelados ou em execução saudável viram no-op.
- Progresso real: atualizado a cada lote com bytes lidos e registros processados.
- Cancelamento cooperativo: verificado entre lotes; o status "cancelado" só é gravado
  depois que a execução realmente parou.
- Publicação atômica: a versão só passa a existir (e a ser a versão atual) na mesma
  transação que marca o job como concluído. Falhas nunca deixam versão parcial visível.
"""

import logging
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import session_scope
from app.models import (
    RUNNING_STATUSES,
    Dataset,
    DatasetStatus,
    DatasetVersion,
    JobStatus,
    ProcessingJob,
    Upload,
)
from app.models.base import utcnow
from app.processing.pipeline import PipelineResult, Progress, file_sha256, run_csv_pipeline
from app.processing.reader import EncodingMismatch, HeaderMismatch
from app.processing.types import ColumnConfig, ParseOptions
from app.services import audit, storage

logger = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class PermanentJobError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class TransientJobError(Exception):
    """Falha transitória (rede, banco, armazenamento): o job volta para a fila."""


TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    *storage.StorageError,
    OperationalError,
    ConnectionError,
    TimeoutError,
)


@dataclass
class JobSnapshot:
    id: uuid.UUID
    workspace_id: uuid.UUID
    dataset_id: uuid.UUID
    created_by_id: uuid.UUID | None
    attempt: int
    max_attempts: int
    config: dict[str, Any]
    rules_version: str
    upload_id: uuid.UUID
    upload_key: str
    upload_sha256: str
    upload_ms: int | None


def _peak_memory_mb() -> float | None:
    try:
        import resource  # indisponível no Windows
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(usage / divisor, 1)


def claim(db: Session, job_id: uuid.UUID) -> bool:
    """Reivindica o job se estiver na fila ou se a execução anterior estiver parada."""
    settings = get_settings()
    now = utcnow()
    stale = now - timedelta(seconds=settings.job_stale_after_seconds)
    result = db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.attempts < ProcessingJob.max_attempts,
            or_(
                ProcessingJob.status == JobStatus.QUEUED,
                (ProcessingJob.status.in_(RUNNING_STATUSES)) & (ProcessingJob.heartbeat_at < stale),
            ),
        )
        .values(
            status=JobStatus.VALIDATING,
            attempts=ProcessingJob.attempts + 1,
            heartbeat_at=now,
            started_at=now,
            finished_at=None,
            error_code=None,
            error_message=None,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    # A sessão não expira objetos no commit; descarta o estado anterior à reivindicação.
    db.expire_all()
    return bool(result.rowcount)  # type: ignore[attr-defined]


def _snapshot(db: Session, job_id: uuid.UUID) -> JobSnapshot:
    job = db.get(ProcessingJob, job_id)
    assert job is not None
    upload = db.get(Upload, job.upload_id)
    assert upload is not None
    return JobSnapshot(
        id=job.id,
        workspace_id=job.workspace_id,
        dataset_id=job.dataset_id,
        created_by_id=job.created_by_id,
        attempt=job.attempts,
        max_attempts=job.max_attempts,
        config=dict(job.config),
        rules_version=job.rules_version,
        upload_id=upload.id,
        upload_key=upload.storage_key,
        upload_sha256=upload.sha256,
        upload_ms=upload.upload_ms,
    )


def _set_status(job_id: uuid.UUID, status: JobStatus) -> None:
    """Muda a etapa e verifica cancelamento solicitado (ponto seguro)."""
    with session_scope() as db:
        db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(status=status, heartbeat_at=utcnow())
        )
        cancel = db.scalar(
            select(ProcessingJob.cancel_requested_at).where(ProcessingJob.id == job_id)
        )
    if cancel is not None:
        raise JobCancelled()


def _report_progress(job_id: uuid.UUID, progress: Progress) -> None:
    with session_scope() as db:
        db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(
                rows_processed=progress.rows_processed,
                bytes_processed=progress.bytes_processed,
                heartbeat_at=utcnow(),
            )
        )
        cancel = db.scalar(
            select(ProcessingJob.cancel_requested_at).where(ProcessingJob.id == job_id)
        )
    if cancel is not None:
        raise JobCancelled()


def _restore_dataset_status(db: Session, dataset_id: uuid.UUID, failed: bool) -> None:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        return
    if dataset.current_version_id is not None:
        dataset.status = DatasetStatus.READY
    else:
        dataset.status = DatasetStatus.FAILED if failed else DatasetStatus.DRAFT


def _finish(
    job_id: uuid.UUID,
    status: JobStatus,
    *,
    code: str | None = None,
    message: str | None = None,
    warning: str | None = None,
) -> None:
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            return
        job.status = status
        job.error_code = code
        job.error_message = message
        job.finished_at = utcnow() if status != JobStatus.QUEUED else None
        if warning:
            job.warnings = [*job.warnings, {"at": utcnow().isoformat(), "message": warning}]
        if status in (JobStatus.FAILED, JobStatus.CANCELLED):
            _restore_dataset_status(db, job.dataset_id, failed=status == JobStatus.FAILED)
            audit.record(
                db,
                "import.failed" if status == JobStatus.FAILED else "import.cancelled",
                workspace_id=job.workspace_id,
                entity_type="job",
                entity_id=job.id,
                details={"error_code": code} if code else {},
            )


def _publish(
    snapshot: JobSnapshot,
    result: PipelineResult,
    columns: list[ColumnConfig],
    timings: dict[str, int],
) -> None:
    assert result.data_path is not None
    prefix = storage.version_prefix(snapshot.workspace_id, snapshot.dataset_id, snapshot.id)
    data_key = prefix + "data.parquet"
    rejected_key = prefix + "rejected.parquet" if result.rejected_path else None

    t0 = time.perf_counter()
    checksum = file_sha256(result.data_path)
    size = result.data_path.stat().st_size
    # Chaves determinísticas por job: uma retentativa sobrescreve o mesmo objeto.
    storage.upload_file(result.data_path, data_key, "application/vnd.apache.parquet")
    if result.rejected_path and rejected_key:
        storage.upload_file(result.rejected_path, rejected_key, "application/vnd.apache.parquet")
    timings["persist_upload"] = int((time.perf_counter() - t0) * 1000)

    with session_scope() as db:
        job = db.get(ProcessingJob, snapshot.id)
        assert job is not None
        if job.cancel_requested_at is not None:
            raise JobCancelled()
        dataset = db.scalar(
            select(Dataset).where(Dataset.id == snapshot.dataset_id).with_for_update()
        )
        assert dataset is not None
        current_max = db.scalar(
            select(DatasetVersion.version_number)
            .where(DatasetVersion.dataset_id == dataset.id)
            .order_by(DatasetVersion.version_number.desc())
            .limit(1)
        )
        version = DatasetVersion(
            workspace_id=snapshot.workspace_id,
            dataset_id=dataset.id,
            version_number=(current_max or 0) + 1,
            job_id=snapshot.id,
            upload_id=snapshot.upload_id,
            created_by_id=snapshot.created_by_id,
            storage_key=data_key,
            rejected_storage_key=rejected_key,
            row_count=result.rows_valid,
            rejected_count=result.rows_rejected,
            size_bytes=size,
            checksum_sha256=checksum,
            column_schema=[
                {
                    "name": c.name,
                    "source_name": c.source_name,
                    "position": c.position,
                    "data_type": c.data_type.value,
                    "format": c.format,
                    "scale": c.scale,
                    "null_count": int(result.null_counts.get(c.name, 0)),
                }
                for c in columns
            ],
            transformations={
                "parse_options": snapshot.config["parse_options"],
                "steps": snapshot.config.get("transformations", []),
            },
            reconciliation=result.reconciliation,
            rules_version=snapshot.rules_version,
        )
        db.add(version)
        db.flush()
        dataset.current_version_id = version.id
        dataset.status = DatasetStatus.READY
        dataset.updated_at = utcnow()

        job.status = JobStatus.SUCCEEDED
        job.finished_at = utcnow()
        job.heartbeat_at = job.finished_at
        job.rows_total = result.rows_total
        job.rows_processed = result.rows_total
        job.rows_valid = result.rows_valid
        job.rows_rejected = result.rows_rejected
        job.bytes_processed = job.bytes_total or job.bytes_processed
        job.result_version_id = version.id
        job.rejection_summary = {
            "by_reason": dict(result.reasons),
            "by_column": dict(result.column_failures),
            "samples": result.samples,
        }
        started = job.started_at or job.queued_at
        timings["total"] = int((job.finished_at - started).total_seconds() * 1000)
        job.metrics = {
            "timings_ms": {"upload": snapshot.upload_ms, **timings},
            "peak_memory_mb": _peak_memory_mb(),
            "rows_per_second": round(
                result.rows_total / max(timings.get("total", 1) / 1000, 0.001), 1
            ),
        }
        audit.record(
            db,
            "dataset.version_published",
            workspace_id=snapshot.workspace_id,
            actor_id=snapshot.created_by_id,
            entity_type="dataset_version",
            entity_id=version.id,
            details={
                "dataset_id": str(dataset.id),
                "version_number": version.version_number,
                "job_id": str(snapshot.id),
            },
        )


def _discard_outputs(snapshot: JobSnapshot) -> None:
    """Remove objetos de uma execução não publicada (nunca de uma versão publicada)."""
    try:
        with session_scope() as db:
            published = db.scalar(
                select(DatasetVersion.id).where(DatasetVersion.job_id == snapshot.id)
            )
        if published is None:
            storage.delete_prefix(
                storage.version_prefix(snapshot.workspace_id, snapshot.dataset_id, snapshot.id)
            )
    except (*storage.StorageError, OperationalError):
        logger.warning("discard_outputs_failed", extra={"job_id": str(snapshot.id)})


def run_import_job(job_id: uuid.UUID) -> str:
    settings = get_settings()
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            logger.warning("job_not_found", extra={"job_id": str(job_id)})
            return "missing"
        cancel_before_start = job.status == JobStatus.QUEUED and job.cancel_requested_at is not None
        if not cancel_before_start:
            if not claim(db, job_id):
                logger.info("job_not_claimed", extra={"job_id": str(job_id), "status": job.status})
                return "skipped"
            snapshot = _snapshot(db, job_id)
    if cancel_before_start:
        _finish(job_id, JobStatus.CANCELLED)
        return "cancelled"

    work = settings.temp_dir / f"job-{job_id}-{snapshot.attempt}"
    log_extra = {"job_id": str(job_id), "attempt": snapshot.attempt}
    logger.info("job_started", extra=log_extra)
    try:
        options = ParseOptions.model_validate(snapshot.config["parse_options"])
        columns = [ColumnConfig.model_validate(c) for c in snapshot.config["columns"]]
        timings: dict[str, int] = {}

        # Etapa: validação
        t0 = time.perf_counter()
        source = work / "original"
        storage.download_file(snapshot.upload_key, source)
        if file_sha256(source) != snapshot.upload_sha256:
            raise PermanentJobError(
                "integridade", "O arquivo original não confere com o hash registrado no envio."
            )
        timings["download_validate"] = int((time.perf_counter() - t0) * 1000)

        # Etapa: processamento
        _set_status(job_id, JobStatus.PROCESSING)
        t1 = time.perf_counter()
        try:
            result = run_csv_pipeline(
                source,
                work / "out",
                options,
                columns,
                snapshot.config.get("expected_header"),
                batch_rows=settings.processing_batch_rows,
                max_field_bytes=settings.max_field_bytes,
                on_progress=lambda progress: _report_progress(job_id, progress),
            )
        except EncodingMismatch as exc:
            raise PermanentJobError(
                "encoding_invalido",
                f"O arquivo contém bytes inválidos para o encoding {options.encoding} "
                f"próximo à linha {exc.line}. Selecione outro encoding e processe novamente.",
            ) from exc
        except HeaderMismatch as exc:
            raise PermanentJobError("cabecalho_divergente", str(exc)) from exc
        timings["processing"] = int((time.perf_counter() - t1) * 1000)
        timings.update({f"processing_{k}": v for k, v in result.timings_ms.items()})
        if not result.reconciliation["consistent"]:
            raise PermanentJobError(
                "reconciliacao", "As contagens de registros não fecharam; nada foi publicado."
            )

        # Etapa: salvamento e publicação
        _set_status(job_id, JobStatus.SAVING)
        _publish(snapshot, result, columns, timings)
        logger.info("job_succeeded", extra={**log_extra, "rows": result.rows_total})
        return "succeeded"
    except JobCancelled:
        _discard_outputs(snapshot)
        _finish(job_id, JobStatus.CANCELLED)
        logger.info("job_cancelled", extra=log_extra)
        return "cancelled"
    except PermanentJobError as exc:
        _discard_outputs(snapshot)
        _finish(job_id, JobStatus.FAILED, code=exc.code, message=exc.message)
        logger.info("job_failed", extra={**log_extra, "error_code": exc.code})
        return "failed"
    except TRANSIENT_ERRORS as exc:
        logger.warning("job_transient_error", extra={**log_extra, "error_type": type(exc).__name__})
        if snapshot.attempt < snapshot.max_attempts:
            _finish(
                job_id,
                JobStatus.QUEUED,
                warning=f"Tentativa {snapshot.attempt} falhou por indisponibilidade temporária; nova tentativa agendada.",
            )
            raise TransientJobError(str(exc)) from exc
        _finish(
            job_id,
            JobStatus.FAILED,
            code="indisponibilidade",
            message="Serviços de armazenamento ou banco indisponíveis após várias tentativas.",
        )
        return "failed"
    except Exception:
        logger.exception("job_crashed", extra=log_extra)
        _finish(
            job_id,
            JobStatus.FAILED,
            code="erro_interno",
            message="Erro interno inesperado durante o processamento.",
        )
        return "failed"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def recover_jobs() -> dict[str, int]:
    """Recupera jobs interrompidos e reenfileira jobs cuja publicação na fila se perdeu."""
    from app.tasks.dispatch import enqueue_import

    settings = get_settings()
    now = utcnow()
    stale = now - timedelta(seconds=settings.job_stale_after_seconds)
    requeue = now - timedelta(seconds=settings.job_requeue_after_seconds)
    stats = {"requeued": 0, "failed": 0, "cancelled": 0, "republished": 0}
    to_enqueue: list[uuid.UUID] = []
    with session_scope() as db:
        stuck = db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.status.in_(RUNNING_STATUSES), ProcessingJob.heartbeat_at < stale)
            .with_for_update(skip_locked=True)
        ).all()
        for job in stuck:
            if job.cancel_requested_at is not None:
                job.status, job.finished_at = JobStatus.CANCELLED, now
                _restore_dataset_status(db, job.dataset_id, failed=False)
                stats["cancelled"] += 1
            elif job.attempts >= job.max_attempts:
                job.status, job.finished_at = JobStatus.FAILED, now
                job.error_code = "interrompido"
                job.error_message = (
                    "A execução foi interrompida repetidamente e excedeu o limite de tentativas."
                )
                _restore_dataset_status(db, job.dataset_id, failed=True)
                stats["failed"] += 1
            else:
                job.status = JobStatus.QUEUED
                job.warnings = [
                    *job.warnings,
                    {"at": now.isoformat(), "message": "Execução interrompida; job reenfileirado."},
                ]
                to_enqueue.append(job.id)
                stats["requeued"] += 1

        cancelled_waiting = db.scalars(
            select(ProcessingJob).where(
                ProcessingJob.status == JobStatus.QUEUED,
                ProcessingJob.cancel_requested_at.is_not(None),
            )
        ).all()
        for job in cancelled_waiting:
            job.status, job.finished_at = JobStatus.CANCELLED, now
            _restore_dataset_status(db, job.dataset_id, failed=False)
            stats["cancelled"] += 1

        lost = db.scalars(
            select(ProcessingJob.id).where(
                ProcessingJob.status == JobStatus.QUEUED,
                ProcessingJob.cancel_requested_at.is_(None),
                or_(ProcessingJob.enqueued_at.is_(None), ProcessingJob.enqueued_at < requeue),
            )
        ).all()
        to_enqueue.extend(job_id for job_id in lost if job_id not in to_enqueue)

    for job_id in to_enqueue:
        if enqueue_import(job_id):
            with session_scope() as db:
                db.execute(
                    update(ProcessingJob)
                    .where(ProcessingJob.id == job_id)
                    .values(enqueued_at=utcnow())
                )
            stats["republished"] += 1
    if any(stats.values()):
        logger.info("jobs_recovered", extra=stats)
    return stats


def cleanup_work_dir(max_age_hours: int = 6) -> int:
    """Remove temporários esquecidos (ex.: worker morto antes do finally)."""
    temp = get_settings().temp_dir
    if not temp.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for entry in temp.iterdir():
        if entry.stat().st_mtime < cutoff:
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            removed += 1
    return removed
