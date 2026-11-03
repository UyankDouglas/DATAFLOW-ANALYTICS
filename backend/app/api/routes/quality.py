import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_db, require
from app.core.permissions import Permission
from app.schemas.quality import (
    InconsistencyPage,
    QualityReportOut,
    QualityVersionSummary,
    ValueFrequency,
)
from app.services import audit, quality_service

router = APIRouter(prefix="/datasets/{dataset_id}", tags=["quality"])


@router.get(
    "/quality",
    response_model=list[QualityVersionSummary],
    summary="Nota e indicadores de qualidade de cada versão (comparação)",
)
def compare_versions(
    dataset_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> list[QualityVersionSummary]:
    return quality_service.compare_versions(db, ctx.workspace_id, dataset_id)


@router.get("/versions/{version_id}/quality", response_model=QualityReportOut)
def get_report(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> QualityReportOut:
    return quality_service.get_report(db, ctx.workspace_id, dataset_id, version_id)


@router.post(
    "/versions/{version_id}/quality",
    response_model=QualityReportOut,
    summary="Calcula (ou recalcula) o relatório de qualidade da versão",
)
def compute_report(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_PROCESS)),
    db: Session = Depends(get_db),
) -> QualityReportOut:
    report = quality_service.compute_for_version(
        db, ctx.workspace_id, dataset_id, version_id, ctx.user.id
    )
    audit.record(
        db,
        "quality.computed",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dataset_version",
        entity_id=version_id,
        details={"dataset_id": str(dataset_id), "score": report.score},
        ip=ctx.ip,
    )
    db.commit()
    return quality_service.report_out_for(db, report)


@router.get(
    "/versions/{version_id}/quality/inconsistencies",
    response_model=InconsistencyPage,
    summary="Registros excluídos com motivo, regra violada e tratamento aplicado",
)
def inconsistencies(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    category: Literal["rejeitado", "filtrado", "duplicado"] | None = None,
    reason: Annotated[str | None, Query(max_length=60)] = None,
    column: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> InconsistencyPage:
    return quality_service.inconsistencies(
        db,
        ctx.workspace_id,
        dataset_id,
        version_id,
        category=category,
        reason=reason,
        column=column,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/versions/{version_id}/quality/values",
    response_model=ValueFrequency,
    summary="Valores mais frequentes de uma coluna",
)
def value_frequency(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    column: Annotated[str, Query(min_length=1, max_length=120)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> ValueFrequency:
    return quality_service.value_frequency(
        db, ctx.workspace_id, dataset_id, version_id, column, limit
    )
