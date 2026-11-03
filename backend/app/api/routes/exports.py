import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_db, require
from app.core.errors import ServiceUnavailable
from app.core.permissions import Permission
from app.schemas.common import Page
from app.schemas.export import ExportOut, ExportRequest
from app.services import export_service, storage

router = APIRouter(prefix="/exports", tags=["exports"])

CHUNK_BYTES = 1024 * 1024


@router.post(
    "",
    response_model=ExportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pede uma exportação CSV ou XLSX (gerada em segundo plano)",
)
def request_export(
    data: ExportRequest,
    ctx: RequestContext = Depends(require(Permission.DATA_EXPORT)),
    db: Session = Depends(get_db),
) -> ExportOut:
    export = export_service.request_export(db, ctx, data)
    return export_service.get_export(db, ctx.workspace_id, export.id)


@router.get("", response_model=Page[ExportOut], summary="Histórico de exportações do workspace")
def list_exports(
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    mine: bool = False,
    ctx: RequestContext = Depends(require(Permission.DATA_EXPORT)),
    db: Session = Depends(get_db),
) -> Page[ExportOut]:
    return export_service.list_exports(
        db, ctx.workspace_id, page=page, page_size=page_size, mine_of=ctx.user.id if mine else None
    )


@router.get("/{export_id}", response_model=ExportOut)
def get_export(
    export_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATA_EXPORT)),
    db: Session = Depends(get_db),
) -> ExportOut:
    return export_service.get_export(db, ctx.workspace_id, export_id)


@router.get(
    "/{export_id}/download",
    response_class=StreamingResponse,
    summary="Baixa o arquivo (transmitido pela API; não há URL pública)",
)
def download_export(
    export_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATA_EXPORT)),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    download = export_service.prepare_download(db, ctx, export_id)
    try:
        body = storage.open_object(download.key)
    except storage.StorageError as exc:
        raise ServiceUnavailable("Não foi possível ler o arquivo agora.") from exc

    def stream() -> Iterator[bytes]:
        try:
            yield from body.iter_chunks(chunk_size=CHUNK_BYTES)
        finally:
            body.close()

    headers = {
        "Content-Disposition": f'attachment; filename="{download.file_name}"',
        "Cache-Control": "no-store",
    }
    if download.size_bytes is not None:
        headers["Content-Length"] = str(download.size_bytes)
    return StreamingResponse(stream(), media_type=download.content_type, headers=headers)


@router.delete("/{export_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_export(
    export_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATA_EXPORT)),
    db: Session = Depends(get_db),
) -> Response:
    export_service.delete_export(db, ctx, export_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
