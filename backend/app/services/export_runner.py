"""Execução das exportações no worker, recuperação de interrompidas e expiração dos arquivos.

O estado vive no PostgreSQL, como nos jobs de processamento (ADR-001): a tarefa reivindica a
exportação com uma atualização condicional, então uma reentrega da fila vira no-op. Os registros
são lidos do Parquet em lotes e escritos direto no arquivo, com memória constante.
"""

import datetime as dt
import logging
import shutil
import time
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.analytics.aggregate import AggregateResult, plan_aggregate, run_aggregate
from app.analytics.cache import local_parquet
from app.analytics.query import build_where, quote_identifier, sandboxed_connection
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import AppError, ServiceUnavailable
from app.models import Dataset, DatasetVersion, ExportJob, ExportStatus, Workspace
from app.models.base import utcnow
from app.processing.export_writers import (
    CONTENT_TYPES,
    CsvStyle,
    ExportColumn,
    write_csv,
    write_xlsx,
)
from app.processing.types import ColumnSpec, DataType
from app.schemas.export import ReportQuery, RowsExport
from app.schemas.workspace import WorkspaceSettings
from app.services import storage
from app.services.export_service import rows_where

logger = logging.getLogger(__name__)

FETCH_ROWS = 5_000


class TransientExportError(Exception):
    """Falha passageira (armazenamento indisponível): a tarefa é reenviada."""


@dataclass(frozen=True)
class ExportSnapshot:
    id: uuid.UUID
    workspace_id: uuid.UUID
    kind: str
    format: str
    params: dict[str, Any]
    dataset_name: str
    version_id: uuid.UUID
    storage_key: str
    checksum: str
    schema: list[ColumnSpec]
    ttl_hours: int
    attempts: int
    max_attempts: int


def claim_export(db: Session, export_id: uuid.UUID) -> bool:
    settings = get_settings()
    now = utcnow()
    stale = now - timedelta(seconds=settings.job_stale_after_seconds)
    result = db.execute(
        update(ExportJob)
        .where(
            ExportJob.id == export_id,
            ExportJob.attempts < ExportJob.max_attempts,
            or_(
                ExportJob.status == ExportStatus.QUEUED,
                (ExportJob.status == ExportStatus.RUNNING) & (ExportJob.heartbeat_at < stale),
            ),
        )
        .values(
            status=ExportStatus.RUNNING,
            attempts=ExportJob.attempts + 1,
            started_at=now,
            heartbeat_at=now,
            error_code=None,
            error_message=None,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.expire_all()
    return bool(result.rowcount)  # type: ignore[attr-defined]


def _snapshot(db: Session, export_id: uuid.UUID) -> ExportSnapshot:
    export = db.get(ExportJob, export_id)
    assert export is not None
    version = db.get(DatasetVersion, export.version_id)
    dataset = db.get(Dataset, export.dataset_id)
    workspace = db.get(Workspace, export.workspace_id)
    assert version is not None
    assert dataset is not None
    assert workspace is not None
    return ExportSnapshot(
        id=export.id,
        workspace_id=export.workspace_id,
        kind=export.kind,
        format=export.format,
        params=export.params,
        dataset_name=dataset.name,
        version_id=version.id,
        storage_key=version.storage_key,
        checksum=version.checksum_sha256,
        schema=[ColumnSpec.model_validate(c) for c in version.column_schema],
        ttl_hours=WorkspaceSettings.model_validate(workspace.settings or {}).export_ttl_hours,
        attempts=export.attempts,
        max_attempts=export.max_attempts,
    )


def _heartbeat(export_id: uuid.UUID) -> None:
    with session_scope() as db:
        db.execute(update(ExportJob).where(ExportJob.id == export_id).values(heartbeat_at=utcnow()))


# ---------------------------------------------------------------- conteúdo


def _rows_source(
    snapshot: ExportSnapshot, path: Path
) -> tuple[list[ExportColumn], Iterator[tuple[Any, ...]]]:
    query = RowsExport.model_validate(snapshot.params.get("rows") or {})
    by_name = {c.name: c for c in snapshot.schema}
    names = query.columns or [c.name for c in snapshot.schema]
    where = rows_where(query, snapshot.schema)
    order = []
    if query.sort:
        order.append(
            f"{quote_identifier(query.sort)} {'DESC' if query.direction == 'desc' else 'ASC'} NULLS LAST"
        )
    order.append("__df_row")
    sql = (
        f"SELECT {', '.join(quote_identifier(n) for n in names)} "  # noqa: S608 - identificadores validados
        f"FROM read_parquet($path){where.apply()} ORDER BY {', '.join(order)}"
    )
    columns = [ExportColumn(n, by_name[n].data_type, by_name[n].scale) for n in names]

    def stream() -> Iterator[tuple[Any, ...]]:
        con = sandboxed_connection(path.parent)
        try:
            cursor = con.execute(sql, {"path": str(path), **where.params})
            while batch := cursor.fetchmany(FETCH_ROWS):
                yield from batch
        finally:
            con.close()

    return columns, stream()


def _typed(value: Any, data_type: str) -> Any:
    """Os resultados analíticos chegam em formato JSON; o arquivo volta a tipá-los."""
    if value is None:
        return None
    try:
        if data_type == DataType.DECIMAL:
            return Decimal(str(value))
        if data_type == DataType.INTEGER:
            return int(value)
        if data_type == DataType.DATE:
            return dt.date.fromisoformat(str(value)[:10])
        if data_type == DataType.DATETIME:
            return dt.datetime.fromisoformat(str(value))
    except (ValueError, InvalidOperation):
        return value
    return value


def _variation(current: Any, previous: Any) -> Decimal | None:
    try:
        now, before = Decimal(str(current)), Decimal(str(previous))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if current is None or previous is None or before == 0:
        return None
    return ((now - before) / abs(before) * 100).quantize(Decimal("0.01"))


def report_table(result: AggregateResult) -> tuple[list[ExportColumn], list[list[Any]]]:
    """Tabela do relatório: grupo, medidas e, com comparação, anterior e variação (%)."""
    columns: list[ExportColumn] = []
    dimension = result.dimension
    if dimension is not None:
        label = dimension.column
        data_type = DataType(dimension.data_type)
        if dimension.granularity:
            label = f"{dimension.column} ({dimension.granularity})"
            data_type = DataType.DATE
        columns.append(ExportColumn(label, data_type))
    for metric in result.metrics:
        columns.append(ExportColumn(metric.label, DataType(metric.data_type), metric.scale))
    if result.comparison:
        for metric in result.metrics:
            columns.append(
                ExportColumn(f"{metric.label} (anterior)", DataType(metric.data_type), metric.scale)
            )
            columns.append(ExportColumn(f"Variação de {metric.label} (%)", DataType.DECIMAL, 2))

    def line(key: Any, values: Sequence[Any], previous: Sequence[Any] | None) -> list[Any]:
        row: list[Any] = []
        if dimension is not None:
            # "Outros (N grupos)" fica como texto; os demais grupos voltam ao tipo da coluna.
            text_key = isinstance(key, str) and not dimension.granularity
            row.append(key if text_key else _typed(key, columns[0].data_type))
        row.extend(_typed(v, m.data_type) for v, m in zip(values, result.metrics, strict=True))
        if result.comparison and previous is not None:
            for index, metric in enumerate(result.metrics):
                row.append(_typed(previous[index], metric.data_type))
                row.append(_variation(values[index], previous[index]))
        return row

    rows = [line(r.key, r.values, r.previous) for r in result.rows]
    if result.others is not None:
        rows.append(
            line(
                f"Outros ({result.others.groups} grupos)",
                result.others.values,
                result.others.previous,
            )
        )
    return columns, rows


def _report_source(
    snapshot: ExportSnapshot, path: Path
) -> tuple[list[ExportColumn], list[list[Any]]]:
    query = ReportQuery.model_validate(snapshot.params["report"])
    extra = tuple(
        build_where(group.filters, group.match, None, snapshot.schema, prefix=f"x{index}_")
        for index, group in enumerate(query.extra_filters)
    )
    plan = plan_aggregate(query, snapshot.schema, extra=extra)
    return report_table(run_aggregate(path, plan))


def _produce(snapshot: ExportSnapshot, parquet: Path, target: Path) -> int:
    rows: Iterable[Sequence[Any]]
    if snapshot.kind == "rows":
        columns, rows = _rows_source(snapshot, parquet)
    else:
        columns, rows = _report_source(snapshot, parquet)

    def progress(_: int) -> None:
        _heartbeat(snapshot.id)

    if snapshot.format == "xlsx":
        return write_xlsx(target, columns, rows, snapshot.dataset_name, progress)
    style: CsvStyle = "padrao" if snapshot.params.get("csv_style") == "padrao" else "excel_br"
    return write_csv(target, columns, rows, style, progress)


# ---------------------------------------------------------------- execução


def _finish(export_id: uuid.UUID, **values: Any) -> None:
    with session_scope() as db:
        db.execute(update(ExportJob).where(ExportJob.id == export_id).values(**values))


def run_export(export_id: uuid.UUID) -> str:
    with session_scope() as db:
        if not claim_export(db, export_id):
            return "skipped"
        snapshot = _snapshot(db, export_id)
    settings = get_settings()
    work = settings.temp_dir / f"export-{export_id}"
    work.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        parquet = local_parquet(f"v-{snapshot.version_id}", snapshot.storage_key, snapshot.checksum)
        target = work / f"arquivo.{snapshot.format}"
        rows = _produce(snapshot, parquet, target)
        key = storage.export_key(snapshot.workspace_id, snapshot.id, snapshot.format)
        storage.upload_file(target, key, CONTENT_TYPES[snapshot.format])
        now = utcnow()
        _finish(
            snapshot.id,
            status=ExportStatus.SUCCEEDED,
            storage_key=key,
            size_bytes=target.stat().st_size,
            row_count=rows,
            finished_at=now,
            expires_at=now + timedelta(hours=snapshot.ttl_hours),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        logger.info(
            "export_succeeded",
            extra={"export_id": str(snapshot.id), "rows": rows, "format": snapshot.format},
        )
        return ExportStatus.SUCCEEDED
    except (ServiceUnavailable, OSError, *storage.StorageError) as exc:
        if snapshot.attempts < snapshot.max_attempts:
            _finish(
                snapshot.id,
                status=ExportStatus.QUEUED,
                error_message="Falha temporária no armazenamento; nova tentativa em seguida.",
            )
            raise TransientExportError(str(exc)) from exc
        _fail(
            snapshot.id,
            "armazenamento",
            "O armazenamento ficou indisponível em todas as tentativas.",
        )
        return ExportStatus.FAILED
    except AppError as exc:
        _fail(snapshot.id, exc.code, exc.message)
        return ExportStatus.FAILED
    except duckdb.Error:
        logger.exception("export_query_failed", extra={"export_id": str(snapshot.id)})
        _fail(snapshot.id, "consulta", "Não foi possível ler os dados da versão.")
        return ExportStatus.FAILED
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _fail(export_id: uuid.UUID, code: str, message: str) -> None:
    _finish(
        export_id,
        status=ExportStatus.FAILED,
        error_code=code[:60],
        error_message=message,
        finished_at=utcnow(),
    )
    logger.warning("export_failed", extra={"export_id": str(export_id), "code": code})


# ---------------------------------------------------------------- manutenção


def recover_exports() -> dict[str, int]:
    """Reenfileira exportações interrompidas ou cuja publicação na fila se perdeu."""
    from app.tasks.dispatch import enqueue_export

    settings = get_settings()
    now = utcnow()
    stale = now - timedelta(seconds=settings.job_stale_after_seconds)
    requeue = now - timedelta(seconds=settings.job_requeue_after_seconds)
    stats = {"requeued": 0, "failed": 0}
    to_enqueue: list[uuid.UUID] = []
    with session_scope() as db:
        stuck = db.scalars(
            select(ExportJob)
            .where(ExportJob.status == ExportStatus.RUNNING, ExportJob.heartbeat_at < stale)
            .with_for_update(skip_locked=True)
        ).all()
        for export in stuck:
            if export.attempts >= export.max_attempts:
                export.status, export.finished_at = ExportStatus.FAILED, now
                export.error_code = "interrompida"
                export.error_message = "A exportação foi interrompida repetidamente."
                stats["failed"] += 1
            else:
                export.status = ExportStatus.QUEUED
                to_enqueue.append(export.id)
                stats["requeued"] += 1
        lost = db.scalars(
            select(ExportJob.id).where(
                ExportJob.status == ExportStatus.QUEUED,
                or_(ExportJob.enqueued_at.is_(None), ExportJob.enqueued_at < requeue),
            )
        ).all()
        to_enqueue.extend(i for i in lost if i not in to_enqueue)
    for export_id in to_enqueue:
        if enqueue_export(export_id):
            with session_scope() as db:
                db.execute(
                    update(ExportJob).where(ExportJob.id == export_id).values(enqueued_at=utcnow())
                )
    return stats


def expire_exports(now: dt.datetime | None = None) -> int:
    """Apaga os arquivos vencidos e marca as exportações como expiradas (o histórico fica)."""
    now = now or utcnow()
    expired = 0
    with session_scope() as db:
        due = db.scalars(
            select(ExportJob)
            .where(ExportJob.status == ExportStatus.SUCCEEDED, ExportJob.expires_at <= now)
            .with_for_update(skip_locked=True)
        ).all()
        for export in due:
            if export.storage_key:
                try:
                    storage.delete_object(export.storage_key)
                except storage.StorageError:
                    logger.warning("export_expire_failed", extra={"export_id": str(export.id)})
                    continue  # tenta de novo na próxima rodada; o download já é recusado
            export.status = ExportStatus.EXPIRED
            export.storage_key = None
            expired += 1
    if expired:
        logger.info("exports_expired", extra={"count": expired})
    return expired
