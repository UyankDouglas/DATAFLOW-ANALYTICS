import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_db, require
from app.core.permissions import Permission
from app.schemas.analytics import AggregateResponse, AnalyticsQuery
from app.schemas.dashboard import (
    DashboardIn,
    DashboardOut,
    DashboardPatch,
    DashboardQuery,
    DashboardSummary,
    WidgetResult,
)
from app.services import analytics_service, dashboards_service

router = APIRouter(tags=["dashboards"])


@router.post(
    "/datasets/{dataset_id}/analytics",
    response_model=AggregateResponse,
    summary="Indicadores de uma versão: medidas, dimensão, filtros e comparação entre períodos",
)
def analytics(
    dataset_id: uuid.UUID,
    data: AnalyticsQuery,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> AggregateResponse:
    return analytics_service.query(db, ctx.workspace_id, dataset_id, data)


@router.get("/dashboards", response_model=list[DashboardSummary])
def list_dashboards(
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> list[DashboardSummary]:
    return dashboards_service.list_dashboards(db, ctx.workspace_id)


@router.post(
    "/dashboards",
    response_model=DashboardOut,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um dashboard (widgets validados contra a versão escolhida)",
)
def create_dashboard(
    data: DashboardIn,
    ctx: RequestContext = Depends(require(Permission.DASHBOARDS_MANAGE)),
    db: Session = Depends(get_db),
) -> DashboardOut:
    return dashboards_service.create_dashboard(db, ctx, data)


@router.get("/dashboards/{dashboard_id}", response_model=DashboardOut)
def get_dashboard(
    dashboard_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> DashboardOut:
    return dashboards_service.get_dashboard(db, ctx.workspace_id, dashboard_id)


@router.patch(
    "/dashboards/{dashboard_id}",
    response_model=DashboardOut,
    summary="Altera nome, versão, filtros ou widgets (a lista enviada define a nova ordem)",
)
def update_dashboard(
    dashboard_id: uuid.UUID,
    data: DashboardPatch,
    ctx: RequestContext = Depends(require(Permission.DASHBOARDS_MANAGE)),
    db: Session = Depends(get_db),
) -> DashboardOut:
    return dashboards_service.update_dashboard(db, ctx, dashboard_id, data)


@router.delete("/dashboards/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashboard(
    dashboard_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DASHBOARDS_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    dashboards_service.delete_dashboard(db, ctx, dashboard_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/dashboards/{dashboard_id}/query",
    response_model=WidgetResult,
    summary="Calcula um widget com os filtros escolhidos na tela",
)
def query_widget(
    dashboard_id: uuid.UUID,
    data: DashboardQuery,
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> WidgetResult:
    return dashboards_service.query_widget(db, ctx.workspace_id, dashboard_id, data)
