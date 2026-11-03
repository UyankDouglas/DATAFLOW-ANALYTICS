import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_db, require
from app.core.permissions import Permission
from app.schemas.job import JobOut
from app.schemas.transformation import (
    DuplicateAnalysisRequest,
    DuplicateAnalysisResponse,
    TransformationSetIn,
    TransformationSetOut,
    TransformJobRequest,
    TransformPreviewRequest,
    TransformPreviewResponse,
)
from app.services import jobs_service, transformation_service

router = APIRouter(prefix="/datasets/{dataset_id}", tags=["transformations"])


@router.get("/transformation-sets", response_model=list[TransformationSetOut])
def list_sets(
    dataset_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> list[TransformationSetOut]:
    return transformation_service.list_sets(db, ctx.workspace_id, dataset_id)


@router.post(
    "/transformation-sets",
    response_model=TransformationSetOut,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um conjunto de regras (validado contra a versão atual)",
)
def create_set(
    dataset_id: uuid.UUID,
    data: TransformationSetIn,
    ctx: RequestContext = Depends(require(Permission.TRANSFORMATIONS_MANAGE)),
    db: Session = Depends(get_db),
) -> TransformationSetOut:
    return transformation_service.create_set(db, ctx, dataset_id, data)


@router.get("/transformation-sets/{set_id}", response_model=TransformationSetOut)
def get_set(
    dataset_id: uuid.UUID,
    set_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> TransformationSetOut:
    return transformation_service.get_set(db, ctx.workspace_id, dataset_id, set_id)


@router.put(
    "/transformation-sets/{set_id}",
    response_model=TransformationSetOut,
    summary="Substitui as regras do conjunto (a revisão é incrementada)",
)
def update_set(
    dataset_id: uuid.UUID,
    set_id: uuid.UUID,
    data: TransformationSetIn,
    ctx: RequestContext = Depends(require(Permission.TRANSFORMATIONS_MANAGE)),
    db: Session = Depends(get_db),
) -> TransformationSetOut:
    return transformation_service.update_set(db, ctx, dataset_id, set_id, data)


@router.delete("/transformation-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_set(
    dataset_id: uuid.UUID,
    set_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.TRANSFORMATIONS_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    transformation_service.delete_set(db, ctx, dataset_id, set_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/transformations/preview",
    response_model=TransformPreviewResponse,
    summary="Aplica regras a uma amostra da versão, sem salvar",
)
def preview(
    dataset_id: uuid.UUID,
    data: TransformPreviewRequest,
    ctx: RequestContext = Depends(require(Permission.TRANSFORMATIONS_MANAGE)),
    db: Session = Depends(get_db),
) -> TransformPreviewResponse:
    return transformation_service.preview(db, ctx.workspace_id, dataset_id, data)


@router.post(
    "/versions/{version_id}/duplicates",
    response_model=DuplicateAnalysisResponse,
    summary="Analisa duplicidades na versão inteira pela chave escolhida",
)
def analyze_duplicates(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    data: DuplicateAnalysisRequest,
    # Só leitura: também alimenta a tela Qualidade, aberta a quem pode ver o dataset.
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> DuplicateAnalysisResponse:
    return transformation_service.analyze_duplicates(
        db, ctx.workspace_id, dataset_id, version_id, data
    )


@router.post(
    "/transform-jobs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Aplica um conjunto de regras a uma versão e gera uma nova versão",
)
def start_transform(
    dataset_id: uuid.UUID,
    data: TransformJobRequest,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
    ctx: RequestContext = Depends(require(Permission.TRANSFORMATIONS_MANAGE)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = transformation_service.start_transform(db, ctx, dataset_id, data, idempotency_key)
    return jobs_service.get_job_out(db, ctx.workspace_id, job.id)
