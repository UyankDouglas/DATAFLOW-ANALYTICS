"""Exportações: pedido validado na API, arquivo gerado pelo worker, download autorizado.

O pedido congela a consulta (filtros, colunas, ordenação ou a consulta do relatório) e a versão.
Antes de enfileirar, a API confere colunas e filtros contra o esquema e conta os registros para
recusar exportações acima do limite. O arquivo fica no armazenamento de objetos, com nome
determinístico, até expirar; só sai pela API, depois da checagem de workspace e permissão.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime

import duckdb
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.analytics.aggregate import plan_aggregate
from app.analytics.cache import local_parquet
from app.analytics.query import WhereClause, build_where, combine_where, count_rows
from app.api.deps import RequestContext
from app.core.config import get_settings
from app.core.errors import (
    Conflict,
    Forbidden,
    Gone,
    NotFound,
    ServiceUnavailable,
    ValidationFailed,
)
from app.core.permissions import Permission
from app.models import (
    ACTIVE_EXPORT_STATUSES,
    Dataset,
    DatasetVersion,
    ExportJob,
    ExportStatus,
    User,
    Workspace,
)
from app.models.base import utcnow
from app.processing.export_writers import CONTENT_TYPES
from app.processing.types import ColumnSpec
from app.repositories import datasets as repo
from app.schemas.common import Page
from app.schemas.export import ExportOut, ExportRequest, RowsExport
from app.schemas.workspace import WorkspaceSettings
from app.services import audit, storage
from app.services.analytics_service import schema_of
from app.tasks.dispatch import enqueue_export


def workspace_settings(db: Session, workspace_id: uuid.UUID) -> WorkspaceSettings:
    raw = db.scalar(select(Workspace.settings).where(Workspace.id == workspace_id))
    return WorkspaceSettings.model_validate(raw or {})


def safe_file_name(
    dataset_name: str, version_number: int, kind: str, fmt: str, now: datetime
) -> str:
    """Nome ASCII previsível para o download; nunca é usado como caminho no armazenamento."""
    ascii_name = unicodedata.normalize("NFKD", dataset_name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60] or "dataset"
    label = "registros" if kind == "rows" else "relatorio"
    return f"{base}_v{version_number}_{label}_{now:%Y%m%d-%H%M}.{fmt}"


def rows_where(rows: RowsExport, schema: list[ColumnSpec]) -> WhereClause:
    """Filtros, busca e grupos extras da exportação de registros, combinados com E."""
    extra = [
        build_where(group.filters, group.match, None, schema, prefix=f"x{index}_")
        for index, group in enumerate(rows.extra_filters)
    ]
    return combine_where(build_where(rows.filters, rows.match, rows.search, schema), *extra)


def _check_rows(data: ExportRequest, version: DatasetVersion) -> int:
    assert data.rows is not None
    settings = get_settings()
    schema = schema_of(version)
    names = [c.name for c in schema]
    unknown = [c for c in data.rows.columns or [] if c not in names]
    if unknown:
        raise ValidationFailed(
            "Há colunas que não existem nesta versão.", code="invalid_columns", details=unknown
        )
    if data.rows.sort is not None and data.rows.sort not in names:
        raise ValidationFailed("Coluna de ordenação desconhecida.", code="invalid_sort")
    where = rows_where(data.rows, schema)
    if where.sql:
        path = local_parquet(f"v-{version.id}", version.storage_key, version.checksum_sha256)
        try:
            rows = count_rows(path, where)
        except duckdb.Error as exc:
            raise ServiceUnavailable("Não foi possível contar os registros agora.") from exc
    else:
        rows = version.row_count
    limit = settings.export_xlsx_max_rows if data.format == "xlsx" else settings.export_max_rows
    if rows == 0:
        raise ValidationFailed("Nenhum registro atende aos filtros.", code="export_empty")
    if rows > limit:
        raise ValidationFailed(
            f"A exportação teria {rows:,} registros; o limite para {data.format.upper()} é "
            f"{limit:,}. Use filtros para reduzir o volume.".replace(",", "."),
            code="export_too_large",
            details={"rows": rows, "limit": limit},
        )
    return rows


def _check_report(data: ExportRequest, version: DatasetVersion) -> None:
    assert data.report is not None
    schema = schema_of(version)
    extra = tuple(
        build_where(group.filters, group.match, None, schema, prefix=f"x{index}_")
        for index, group in enumerate(data.report.extra_filters)
    )
    plan_aggregate(data.report, schema, extra=extra)


def request_export(db: Session, ctx: RequestContext, data: ExportRequest) -> ExportJob:
    dataset = repo.get_dataset(db, ctx.workspace_id, data.dataset_id)
    version = repo.resolve_version(db, ctx.workspace_id, dataset.id, data.version_id)
    estimated = _check_rows(data, version) if data.kind == "rows" else None
    if data.kind == "report":
        _check_report(data, version)
    settings = get_settings()
    active = db.scalar(
        select(func.count())
        .select_from(ExportJob)
        .where(
            ExportJob.workspace_id == ctx.workspace_id,
            ExportJob.status.in_(ACTIVE_EXPORT_STATUSES),
        )
    )
    if (active or 0) >= settings.export_active_per_workspace:
        raise Conflict(
            f"Já há {active} exportações em andamento neste workspace. Aguarde uma terminar.",
            code="too_many_exports",
        )
    export = ExportJob(
        workspace_id=ctx.workspace_id,
        dataset_id=dataset.id,
        version_id=version.id,
        created_by_id=ctx.user.id,
        kind=data.kind,
        format=data.format,
        params={
            **data.model_dump(mode="json", include={"csv_style", "rows", "report"}),
            "estimated_rows": estimated,
        },
        file_name=safe_file_name(
            dataset.name, version.version_number, data.kind, data.format, utcnow()
        ),
    )
    db.add(export)
    db.flush()
    audit.record(
        db,
        "export.requested",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="export",
        entity_id=export.id,
        details={
            "dataset_id": str(dataset.id),
            "version_id": str(version.id),
            "kind": data.kind,
            "format": data.format,
            "estimated_rows": estimated,
        },
        ip=ctx.ip,
    )
    db.commit()
    if enqueue_export(export.id):
        export.enqueued_at = utcnow()
        db.commit()
    return export


# ---------------------------------------------------------------- leitura


def _get(db: Session, workspace_id: uuid.UUID, export_id: uuid.UUID) -> ExportJob:
    export = db.scalar(
        select(ExportJob).where(ExportJob.id == export_id, ExportJob.workspace_id == workspace_id)
    )
    if export is None:
        raise NotFound("Exportação não encontrada.")
    return export


def _out(
    export: ExportJob, dataset_name: str, version_number: int, creator: str | None
) -> ExportOut:
    return ExportOut(
        id=export.id,
        dataset_id=export.dataset_id,
        dataset_name=dataset_name,
        version_id=export.version_id,
        version_number=version_number,
        kind=export.kind,
        format=export.format,
        status=export.status,
        file_name=export.file_name,
        params=export.params,
        estimated_rows=export.params.get("estimated_rows"),
        row_count=export.row_count,
        size_bytes=export.size_bytes,
        error_code=export.error_code,
        error_message=export.error_message,
        created_by_name=creator,
        created_at=export.created_at,
        started_at=export.started_at,
        finished_at=export.finished_at,
        expires_at=export.expires_at,
        duration_ms=export.duration_ms,
        download_count=export.download_count,
    )


def _query() -> Select[ExportJob, str, int, str]:
    return (
        select(ExportJob, Dataset.name, DatasetVersion.version_number, User.full_name)
        .join(Dataset, Dataset.id == ExportJob.dataset_id)
        .join(DatasetVersion, DatasetVersion.id == ExportJob.version_id)
        .outerjoin(User, User.id == ExportJob.created_by_id)
    )


def list_exports(
    db: Session, workspace_id: uuid.UUID, *, page: int, page_size: int, mine_of: uuid.UUID | None
) -> Page[ExportOut]:
    query = _query().where(ExportJob.workspace_id == workspace_id)
    count = (
        select(func.count()).select_from(ExportJob).where(ExportJob.workspace_id == workspace_id)
    )
    if mine_of is not None:
        query = query.where(ExportJob.created_by_id == mine_of)
        count = count.where(ExportJob.created_by_id == mine_of)
    rows = db.execute(
        query.order_by(ExportJob.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    ).all()
    return Page(
        items=[_out(export, name, number, creator) for export, name, number, creator in rows],
        total=int(db.scalar(count) or 0),
        page=page,
        page_size=page_size,
    )


def get_export(db: Session, workspace_id: uuid.UUID, export_id: uuid.UUID) -> ExportOut:
    row = db.execute(
        _query().where(ExportJob.id == export_id, ExportJob.workspace_id == workspace_id)
    ).first()
    if row is None:
        raise NotFound("Exportação não encontrada.")
    export, name, number, creator = row
    return _out(export, name, number, creator)


# ---------------------------------------------------------------- download e remoção


@dataclass
class Download:
    key: str
    file_name: str
    content_type: str
    size_bytes: int | None


def prepare_download(db: Session, ctx: RequestContext, export_id: uuid.UUID) -> Download:
    export = _get(db, ctx.workspace_id, export_id)
    now = utcnow()
    if export.status == ExportStatus.EXPIRED or (
        export.status == ExportStatus.SUCCEEDED
        and export.expires_at is not None
        and export.expires_at <= now
    ):
        raise Gone(
            "Esta exportação expirou e o arquivo foi apagado. Gere uma nova.",
            code="export_expired",
        )
    if export.status != ExportStatus.SUCCEEDED or export.storage_key is None:
        raise Conflict("A exportação ainda não está pronta.", code="export_not_ready")
    export.download_count += 1
    export.last_downloaded_at = now
    audit.record(
        db,
        "export.downloaded",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="export",
        entity_id=export.id,
        details={"format": export.format, "rows": export.row_count},
        ip=ctx.ip,
    )
    db.commit()
    return Download(
        key=export.storage_key,
        file_name=export.file_name,
        content_type=CONTENT_TYPES[export.format],
        size_bytes=export.size_bytes,
    )


def delete_export(db: Session, ctx: RequestContext, export_id: uuid.UUID) -> None:
    export = _get(db, ctx.workspace_id, export_id)
    if export.created_by_id != ctx.user.id and not ctx.can(Permission.WORKSPACE_MANAGE):
        raise Forbidden("Só quem pediu a exportação ou um administrador pode excluí-la.")
    if export.status in ACTIVE_EXPORT_STATUSES:
        raise Conflict("A exportação ainda está em andamento.", code="export_running")
    if export.storage_key:
        try:
            storage.delete_object(export.storage_key)
        except storage.StorageError as exc:
            raise ServiceUnavailable("Não foi possível apagar o arquivo agora.") from exc
    audit.record(
        db,
        "export.deleted",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="export",
        entity_id=export.id,
        details={"status": export.status},
        ip=ctx.ip,
    )
    db.delete(export)
    db.commit()
