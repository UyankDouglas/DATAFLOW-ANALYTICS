import uuid
from typing import Annotated, Literal
from urllib.parse import unquote

import anyio
from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_db, require
from app.core.config import get_settings
from app.core.permissions import Permission
from app.processing.inspection import FileRejected
from app.processing.types import ParseOptions
from app.repositories import datasets as repo
from app.schemas.common import Message, Page
from app.schemas.dataset import (
    DatasetColumnOut,
    DatasetDetail,
    DatasetListItem,
    DatasetOut,
    DatasetVersionOut,
    ImportRequest,
    PreviewResponse,
    RejectedRowsResponse,
    RowsResponse,
    UploadOut,
    UploadResponse,
)
from app.schemas.job import JobOut
from app.services import (
    audit,
    datasets_service,
    import_service,
    jobs_service,
    preview_service,
    upload_service,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])

PageParam = Annotated[int, Query(ge=1, le=100_000)]


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Envia um CSV (corpo binário em streaming)",
    description=(
        "Envie o arquivo como corpo bruto da requisição (`application/octet-stream`) e o nome no "
        "cabeçalho `X-File-Name` (URL-encoded). O limite de tamanho é aplicado durante o recebimento."
    ),
)
async def upload_dataset(
    request: Request,
    x_file_name: Annotated[str, Header(max_length=600)],
    dataset_name: Annotated[str | None, Query(max_length=160)] = None,
    ctx: RequestContext = Depends(require(Permission.DATASETS_UPLOAD)),
    db: Session = Depends(get_db),
) -> UploadResponse:
    filename = unquote(x_file_name)
    raw_length = request.headers.get("content-length")
    content_length = int(raw_length) if raw_length and raw_length.isdigit() else None
    safe_name = await anyio.to_thread.run_sync(
        upload_service.check_upload_request, ctx, filename, content_length
    )

    settings = get_settings()
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4()
    temp_path = settings.temp_dir / f"upload-{upload_id}"
    try:
        try:
            detection, upload_ms = await upload_service.spool_to_disk(request.stream(), temp_path)
        except FileRejected as exc:
            raise await anyio.to_thread.run_sync(
                upload_service.record_rejection, db, ctx, exc, safe_name
            ) from exc
        dataset, upload = await anyio.to_thread.run_sync(
            lambda: upload_service.store_upload(
                db,
                ctx,
                upload_id=upload_id,
                temp_path=temp_path,
                filename=safe_name,
                detection=detection,
                upload_ms=upload_ms,
                dataset_name=dataset_name,
            )
        )
    finally:
        temp_path.unlink(missing_ok=True)
    return UploadResponse(
        dataset=DatasetOut.model_validate(dataset), upload=UploadOut.model_validate(upload)
    )


@router.get("", response_model=Page[DatasetListItem])
def list_datasets(
    page: PageParam = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status_filter: Annotated[
        str | None, Query(alias="status", pattern="^(draft|processing|ready|failed)$")
    ] = None,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> Page[DatasetListItem]:
    return datasets_service.list_datasets(
        db, ctx.workspace_id, page=page, page_size=page_size, search=search, status=status_filter
    )


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(
    dataset_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> DatasetDetail:
    return datasets_service.get_detail(db, ctx.workspace_id, dataset_id)


@router.get(
    "/{dataset_id}/preview",
    response_model=PreviewResponse,
    summary="Pré-visualização com opções salvas",
)
def get_preview(
    dataset_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> PreviewResponse:
    return preview_service.build_preview(db, ctx.workspace_id, dataset_id, None)


@router.post(
    "/{dataset_id}/preview",
    response_model=PreviewResponse,
    summary="Pré-visualização com opções de teste (não salva)",
)
def try_preview(
    dataset_id: uuid.UUID,
    options: ParseOptions,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> PreviewResponse:
    return preview_service.build_preview(db, ctx.workspace_id, dataset_id, options)


@router.put("/{dataset_id}/parse-options", response_model=Message)
def save_parse_options(
    dataset_id: uuid.UUID,
    options: ParseOptions,
    ctx: RequestContext = Depends(require(Permission.DATASETS_PROCESS)),
    db: Session = Depends(get_db),
) -> Message:
    dataset = repo.get_dataset(db, ctx.workspace_id, dataset_id)
    dataset.parse_options = options.model_dump()
    audit.record(
        db,
        "dataset.parse_options_updated",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dataset",
        entity_id=dataset.id,
        ip=ctx.ip,
    )
    db.commit()
    return Message(message="Configuração de leitura salva.")


@router.get("/{dataset_id}/columns", response_model=list[DatasetColumnOut])
def get_columns(
    dataset_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> list[DatasetColumnOut]:
    dataset = repo.get_dataset(db, ctx.workspace_id, dataset_id)
    return [DatasetColumnOut.model_validate(c) for c in dataset.columns]


@router.get("/{dataset_id}/versions", response_model=list[DatasetVersionOut])
def get_versions(
    dataset_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> list[DatasetVersionOut]:
    return datasets_service.list_versions(db, ctx.workspace_id, dataset_id)


@router.post(
    "/{dataset_id}/imports",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Inicia o processamento",
)
def start_import(
    dataset_id: uuid.UUID,
    data: ImportRequest,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
    ctx: RequestContext = Depends(require(Permission.DATASETS_PROCESS)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = import_service.start_import(db, ctx, dataset_id, data, idempotency_key)
    return jobs_service.get_job_out(db, ctx.workspace_id, job.id)


@router.get(
    "/{dataset_id}/rows",
    response_model=RowsResponse,
    summary="Registros processados (paginação no servidor)",
)
def get_rows(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    page: PageParam = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: Annotated[str | None, Query(max_length=63)] = None,
    direction: Literal["asc", "desc"] = "asc",
    columns: Annotated[str | None, Query(max_length=8000)] = None,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> RowsResponse:
    selected = [c for c in columns.split(",") if c] if columns else None
    return datasets_service.get_rows(
        db,
        ctx.workspace_id,
        dataset_id,
        version_id=version_id,
        page=page,
        page_size=page_size,
        sort=sort,
        direction=direction,
        columns=selected,
    )


@router.get("/{dataset_id}/versions/{version_id}/rejected", response_model=RejectedRowsResponse)
def get_rejected(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    page: PageParam = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> RejectedRowsResponse:
    return datasets_service.get_rejected_rows(
        db, ctx.workspace_id, dataset_id, version_id, page=page, page_size=page_size
    )
