import uuid
from typing import Literal

import duckdb
import pyarrow.parquet as pq
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.cache import local_parquet
from app.analytics.query import WhereClause, build_where, count_rows, fetch_page
from app.core.errors import NotFound, ServiceUnavailable
from app.models import Dataset, DatasetVersion, ProcessingJob, QualityReport, Upload, User
from app.processing.convert import META_COLUMNS
from app.processing.types import ColumnSpec
from app.repositories import datasets as repo
from app.schemas.common import Page
from app.schemas.dataset import (
    DatasetColumnOut,
    DatasetDetail,
    DatasetListItem,
    DatasetVersionOut,
    RejectedRowsResponse,
    RowsResponse,
    UploadOut,
)
from app.schemas.quality import RowsQuery


def list_datasets(
    db: Session,
    workspace_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
    search: str | None,
    status: str | None,
) -> Page[DatasetListItem]:
    filters = [Dataset.workspace_id == workspace_id]
    if search:
        filters.append(Dataset.name.ilike(f"%{search.replace('%', '').replace('_', ' ')}%"))
    if status:
        filters.append(Dataset.status == status)
    total = db.scalar(select(func.count()).select_from(Dataset).where(*filters)) or 0
    rows = db.execute(
        select(Dataset, DatasetVersion.version_number, DatasetVersion.row_count)
        .outerjoin(DatasetVersion, DatasetVersion.id == Dataset.current_version_id)
        .where(*filters)
        .order_by(Dataset.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    dataset_ids = [d.id for d, _, _ in rows]
    uploads: dict[uuid.UUID, Upload] = {}
    jobs: dict[uuid.UUID, ProcessingJob] = {}
    if dataset_ids:
        for found_upload in db.scalars(
            select(Upload).where(Upload.dataset_id.in_(dataset_ids)).order_by(Upload.created_at)
        ):
            uploads[found_upload.dataset_id] = found_upload
        for found_job in db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.dataset_id.in_(dataset_ids))
            .order_by(ProcessingJob.created_at)
        ):
            jobs[found_job.dataset_id] = found_job
    items = []
    for dataset, version_number, row_count in rows:
        item = DatasetListItem.model_validate(dataset)
        item.current_version_number = version_number
        item.row_count = row_count
        upload = uploads.get(dataset.id)
        item.latest_upload = UploadOut.model_validate(upload) if upload else None
        job = jobs.get(dataset.id)
        item.latest_job_id = job.id if job else None
        item.latest_job_status = job.status if job else None
        items.append(item)
    return Page[DatasetListItem](items=items, total=total, page=page, page_size=page_size)


def _version_out(
    version: DatasetVersion,
    user_name: str | None,
    numbers: dict[uuid.UUID, int] | None = None,
    quality_score: float | None = None,
) -> DatasetVersionOut:
    out = DatasetVersionOut.model_validate(version)
    out.created_by_name = user_name
    out.quality_score = quality_score
    if version.parent_version_id and numbers is not None:
        out.parent_version_number = numbers.get(version.parent_version_id)
    return out


def _version_numbers(db: Session, dataset_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(DatasetVersion.id, DatasetVersion.version_number).where(
            DatasetVersion.dataset_id == dataset_id
        )
    ).all()
    return {row[0]: row[1] for row in rows}


def get_detail(db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID) -> DatasetDetail:
    dataset = repo.get_dataset(db, workspace_id, dataset_id)
    upload = repo.latest_upload(db, dataset.id)
    current = None
    if dataset.current_version_id:
        row = db.execute(
            select(DatasetVersion, User.full_name, QualityReport.score)
            .outerjoin(User, User.id == DatasetVersion.created_by_id)
            .outerjoin(QualityReport, QualityReport.version_id == DatasetVersion.id)
            .where(DatasetVersion.id == dataset.current_version_id)
        ).first()
        if row:
            version, name, score = row
            current = _version_out(version, name, _version_numbers(db, dataset.id), score)
    return DatasetDetail(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        status=dataset.status,
        source_format=dataset.source_format,
        current_version_id=dataset.current_version_id,
        created_by_id=dataset.created_by_id,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
        parse_options=dataset.parse_options,
        columns=[DatasetColumnOut.model_validate(c) for c in dataset.columns],
        latest_upload=UploadOut.model_validate(upload) if upload else None,
        current_version=current,
    )


def list_versions(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID
) -> list[DatasetVersionOut]:
    repo.get_dataset(db, workspace_id, dataset_id)
    rows = db.execute(
        select(DatasetVersion, User.full_name, QualityReport.score)
        .outerjoin(User, User.id == DatasetVersion.created_by_id)
        .outerjoin(QualityReport, QualityReport.version_id == DatasetVersion.id)
        .where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.workspace_id == workspace_id)
        .order_by(DatasetVersion.version_number.desc())
    ).all()
    numbers = {version.id: version.version_number for version, _, _ in rows}
    return [_version_out(version, name, numbers, score) for version, name, score in rows]


def _resolve_version(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, version_id: uuid.UUID | None
) -> DatasetVersion:
    dataset = repo.get_dataset(db, workspace_id, dataset_id)
    target = version_id or dataset.current_version_id
    if target is None:
        raise NotFound("Este dataset ainda não possui versão processada.", code="no_version")
    return repo.get_version(db, workspace_id, dataset_id, target)


def get_rows(
    db: Session,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    *,
    version_id: uuid.UUID | None,
    page: int,
    page_size: int,
    sort: str | None,
    direction: Literal["asc", "desc"],
    columns: list[str] | None,
    query: RowsQuery | None = None,
) -> RowsResponse:
    version = _resolve_version(db, workspace_id, dataset_id, version_id)
    schema = version.column_schema
    names = [c["name"] for c in schema]
    where = WhereClause()
    if query is not None:
        specs = [ColumnSpec.model_validate(c) for c in schema]
        where = build_where(query.filters, query.match, query.search, specs)
    path = local_parquet(f"v-{version.id}", version.storage_key, version.checksum_sha256)
    try:
        result = fetch_page(
            path,
            names,
            columns=columns,
            sort=sort,
            direction=direction,
            limit=page_size,
            offset=(page - 1) * page_size,
            where=where,
        )
        total = count_rows(path, where) if where.sql else version.row_count
    except duckdb.Error as exc:
        raise ServiceUnavailable("Não foi possível consultar os dados agora.") from exc
    by_name = {c["name"]: c for c in schema}
    return RowsResponse(
        version_id=version.id,
        version_number=version.version_number,
        columns=[
            {
                "name": n,
                "data_type": by_name[n]["data_type"],
                "format": by_name[n].get("format"),
                "scale": by_name[n].get("scale"),
            }
            for n in result.columns
        ],
        rows=result.rows,
        total=total,
        total_unfiltered=version.row_count,
        page=page,
        page_size=page_size,
    )


def query_rows(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, query: RowsQuery
) -> RowsResponse:
    """Consulta do Data Explorer: filtros tipados, busca, colunas escolhidas e ordenação."""
    return get_rows(
        db,
        workspace_id,
        dataset_id,
        version_id=query.version_id,
        page=query.page,
        page_size=query.page_size,
        sort=query.sort,
        direction=query.direction,
        columns=query.columns,
        query=query,
    )


def get_rejected_rows(
    db: Session,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
) -> RejectedRowsResponse:
    version = repo.get_version(db, workspace_id, dataset_id, version_id)
    excluded = version.rejected_count + version.filtered_count + (version.duplicate_count or 0)
    if not version.rejected_storage_key or excluded == 0:
        names = [*META_COLUMNS, *[c["name"] for c in version.column_schema]]
        return RejectedRowsResponse(
            version_id=version.id, columns=names, rows=[], total=0, page=page, page_size=page_size
        )
    path = local_parquet(f"r-{version.id}", version.rejected_storage_key)
    # Colunas do próprio arquivo: versões antigas têm menos metadados, e nas transformações
    # os valores originais são os da versão de entrada.
    names = pq.read_schema(path).names
    try:
        result = fetch_page(
            path,
            names,
            columns=None,
            sort=None,
            direction="asc",
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    except duckdb.Error as exc:
        raise ServiceUnavailable(
            "Não foi possível consultar os registros rejeitados agora."
        ) from exc
    return RejectedRowsResponse(
        version_id=version.id,
        columns=result.columns,
        rows=result.rows,
        total=excluded,
        page=page,
        page_size=page_size,
    )
