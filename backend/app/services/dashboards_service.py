"""Dashboards persistidos: dataset e versão, filtros gerais e widgets com consultas validadas.

Cada widget guarda só a definição da consulta (medidas, dimensão, filtros…), validada contra o
esquema da versão ao salvar. Os números são sempre recalculados a partir do Parquet, então um
dashboard que acompanha a versão atual mostra os dados novos assim que ela é publicada.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analytics.aggregate import AggregateSpec, plan_aggregate
from app.analytics.query import build_where
from app.api.deps import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models import Dashboard, DashboardWidget, Dataset, DatasetVersion, User
from app.models.base import utcnow
from app.processing.types import ColumnSpec
from app.repositories import datasets as repo
from app.schemas.analytics import FilterSet
from app.schemas.dashboard import (
    DashboardIn,
    DashboardOut,
    DashboardPatch,
    DashboardQuery,
    DashboardSummary,
    WidgetIn,
    WidgetOut,
    WidgetResult,
)
from app.services import audit
from app.services.analytics_service import run_on_version, schema_of

# Partes de um todo: média, mínimo ou máximo por fatia não somam 100%.
PART_OF_WHOLE = {"count", "sum"}


def check_chart_rules(chart_type: str, spec: AggregateSpec, schema: list[ColumnSpec]) -> None:
    """Combinações de gráfico e consulta que fazem sentido. Erros em ValueError."""
    if chart_type == "kpi":
        if spec.dimension is not None:
            raise ValueError("um card KPI mostra um único número: remova a dimensão")
        if len(spec.metrics) != 1:
            raise ValueError("um card KPI usa exatamente uma medida")
        return
    if spec.dimension is None:
        raise ValueError("escolha a dimensão do gráfico")
    temporal = any(
        c.name == spec.dimension.column and c.data_type in {"date", "datetime"} for c in schema
    )
    if chart_type in {"pie", "donut"}:
        if temporal:
            raise ValueError("gráficos de pizza e rosca usam uma dimensão de categoria")
        if len(spec.metrics) != 1 or spec.metrics[0].aggregation not in PART_OF_WHOLE:
            raise ValueError(
                "gráficos de pizza e rosca mostram partes de um todo: use uma única medida "
                "de contagem ou soma"
            )
        if spec.comparison is not None:
            raise ValueError("gráficos de pizza e rosca não comparam períodos")
    if chart_type in {"line", "area"} and spec.comparison is not None:
        raise ValueError("gráficos de linha e área já mostram a evolução; remova a comparação")


def _validate_dashboard(
    widgets: list[WidgetIn], filters: FilterSet, schema: list[ColumnSpec], version_number: int
) -> None:
    build_where(filters.filters, filters.match, None, schema, label="Filtro do dashboard")
    for index, widget in enumerate(widgets):
        try:
            check_chart_rules(widget.chart_type, widget.query, schema)
            plan_aggregate(widget.query, schema)
        except ValueError as exc:
            raise ValidationFailed(
                f"Widget {index + 1} ({widget.title}): {exc}.",
                code="invalid_widget",
                details={"widget_index": index},
            ) from exc
        except ValidationFailed as exc:
            raise ValidationFailed(
                f"Widget {index + 1} ({widget.title}): {exc.message}",
                code="invalid_widget",
                details={"widget_index": index, "reason": exc.code, "version": version_number},
            ) from exc


def _get(db: Session, workspace_id: uuid.UUID, dashboard_id: uuid.UUID) -> Dashboard:
    dashboard = db.scalar(
        select(Dashboard).where(
            Dashboard.id == dashboard_id, Dashboard.workspace_id == workspace_id
        )
    )
    if dashboard is None:
        raise NotFound("Dashboard não encontrado.")
    return dashboard


def _target_version(
    db: Session, workspace_id: uuid.UUID, dataset: Dataset, version_id: uuid.UUID | None
) -> DatasetVersion:
    """Versão fixada (do mesmo dataset e workspace) ou a atual; exige uma versão publicada."""
    if version_id is not None:
        return repo.get_version(db, workspace_id, dataset.id, version_id)
    if dataset.current_version_id is None:
        raise ValidationFailed(
            "Processe o dataset antes de criar um dashboard com ele.", code="no_version"
        )
    version = db.get(DatasetVersion, dataset.current_version_id)
    assert version is not None
    return version


def _names(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(wanted))).all())


def _out(db: Session, dashboard: Dashboard) -> DashboardOut:
    dataset = db.get(Dataset, dashboard.dataset_id)
    assert dataset is not None
    pinned = db.get(DatasetVersion, dashboard.version_id) if dashboard.version_id else None
    resolved_id = dashboard.version_id or dataset.current_version_id
    resolved = pinned or (db.get(DatasetVersion, resolved_id) if resolved_id else None)
    names = _names(db, {dashboard.created_by_id, dashboard.updated_by_id})
    return DashboardOut(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        version_id=dashboard.version_id,
        version_number=pinned.version_number if pinned else None,
        resolved_version_id=resolved.id if resolved else None,
        resolved_version_number=resolved.version_number if resolved else None,
        filters=FilterSet.model_validate(dashboard.filters or {}),
        widgets=[
            WidgetOut(
                id=w.id,
                position=w.position,
                title=w.title,
                chart_type=w.chart_type,
                size=w.size,
                query=AggregateSpec.model_validate(w.config),
            )
            for w in dashboard.widgets
        ],
        created_by_name=names.get(dashboard.created_by_id) if dashboard.created_by_id else None,
        updated_by_name=names.get(dashboard.updated_by_id) if dashboard.updated_by_id else None,
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
    )


def _ensure_unique_name(
    db: Session, workspace_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    query = select(Dashboard.id).where(
        Dashboard.workspace_id == workspace_id, Dashboard.name == name
    )
    if exclude is not None:
        query = query.where(Dashboard.id != exclude)
    if db.scalar(query) is not None:
        raise Conflict("Já existe um dashboard com este nome no workspace.", code="duplicate_name")


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(
            "Já existe um dashboard com este nome no workspace.", code="duplicate_name"
        ) from exc


def _widget_config(widget: WidgetIn) -> dict[str, Any]:
    return widget.query.model_dump(mode="json", exclude_defaults=True)


def _replace_widgets(db: Session, dashboard: Dashboard, widgets: list[WidgetIn]) -> None:
    """Grava a lista na ordem recebida, mantendo o id dos widgets que já existiam."""
    existing = {w.id: w for w in dashboard.widgets}
    unknown = [w.id for w in widgets if w.id is not None and w.id not in existing]
    if unknown:
        raise ValidationFailed(
            "Um dos widgets não pertence a este dashboard.", code="unknown_widget"
        )
    kept = {w.id for w in widgets if w.id is not None}
    for widget in list(dashboard.widgets):
        if widget.id not in kept:
            dashboard.widgets.remove(widget)
    # Posições provisórias evitam colisão com a restrição única durante a troca de ordem.
    for offset, widget in enumerate(dashboard.widgets):
        widget.position = -(offset + 1)
    db.flush()
    for position, data in enumerate(widgets):
        row = existing.get(data.id) if data.id is not None else None
        if row is None:
            row = DashboardWidget(dashboard_id=dashboard.id)
            dashboard.widgets.append(row)
        row.position = position
        row.title = data.title
        row.chart_type = data.chart_type
        row.size = data.size
        row.config = _widget_config(data)
        row.updated_at = utcnow()
    db.flush()
    dashboard.widgets.sort(key=lambda w: w.position)


# ---------------------------------------------------------------- leitura


def list_dashboards(db: Session, workspace_id: uuid.UUID) -> list[DashboardSummary]:
    counts = (
        select(DashboardWidget.dashboard_id, func.count().label("n"))
        .group_by(DashboardWidget.dashboard_id)
        .subquery()
    )
    rows = db.execute(
        select(Dashboard, Dataset.name, DatasetVersion.version_number, counts.c.n)
        .join(Dataset, Dataset.id == Dashboard.dataset_id)
        .outerjoin(DatasetVersion, DatasetVersion.id == Dashboard.version_id)
        .outerjoin(counts, counts.c.dashboard_id == Dashboard.id)
        .where(Dashboard.workspace_id == workspace_id)
        .order_by(Dashboard.updated_at.desc())
    ).all()
    dashboards = [row[0] for row in rows]
    types: dict[uuid.UUID, list[str]] = {}
    if dashboards:
        for dashboard_id, chart_type in db.execute(
            select(DashboardWidget.dashboard_id, DashboardWidget.chart_type)
            .where(DashboardWidget.dashboard_id.in_([d.id for d in dashboards]))
            .order_by(DashboardWidget.position)
        ).all():
            types.setdefault(dashboard_id, []).append(chart_type)
    names = _names(db, {d.updated_by_id for d in dashboards})
    return [
        DashboardSummary(
            id=dashboard.id,
            name=dashboard.name,
            description=dashboard.description,
            dataset_id=dashboard.dataset_id,
            dataset_name=dataset_name,
            version_id=dashboard.version_id,
            version_number=version_number,
            widget_count=int(count or 0),
            chart_types=types.get(dashboard.id, []),
            updated_by_name=names.get(dashboard.updated_by_id) if dashboard.updated_by_id else None,
            updated_at=dashboard.updated_at,
        )
        for dashboard, dataset_name, version_number, count in rows
    ]


def get_dashboard(db: Session, workspace_id: uuid.UUID, dashboard_id: uuid.UUID) -> DashboardOut:
    return _out(db, _get(db, workspace_id, dashboard_id))


# ---------------------------------------------------------------- escrita


def create_dashboard(db: Session, ctx: RequestContext, data: DashboardIn) -> DashboardOut:
    dataset = repo.get_dataset(db, ctx.workspace_id, data.dataset_id)
    version = _target_version(db, ctx.workspace_id, dataset, data.version_id)
    _validate_dashboard(data.widgets, data.filters, schema_of(version), version.version_number)
    _ensure_unique_name(db, ctx.workspace_id, data.name)
    if any(w.id is not None for w in data.widgets):
        raise ValidationFailed("Widgets novos não têm id.", code="unknown_widget")
    dashboard = Dashboard(
        workspace_id=ctx.workspace_id,
        dataset_id=dataset.id,
        version_id=data.version_id,
        name=data.name,
        description=data.description,
        filters=data.filters.model_dump(mode="json"),
        created_by_id=ctx.user.id,
        updated_by_id=ctx.user.id,
    )
    db.add(dashboard)
    db.flush()
    _replace_widgets(db, dashboard, data.widgets)
    audit.record(
        db,
        "dashboard.created",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dashboard",
        entity_id=dashboard.id,
        details={"dataset_id": str(dataset.id), "widgets": len(data.widgets)},
        ip=ctx.ip,
    )
    _commit(db)
    return _out(db, dashboard)


def update_dashboard(
    db: Session, ctx: RequestContext, dashboard_id: uuid.UUID, data: DashboardPatch
) -> DashboardOut:
    dashboard = _get(db, ctx.workspace_id, dashboard_id)
    changed = data.model_fields_set
    dataset_id = data.dataset_id if data.dataset_id is not None else dashboard.dataset_id
    dataset = repo.get_dataset(db, ctx.workspace_id, dataset_id)
    if "version_id" in changed:
        version_id = data.version_id
    elif dataset_id != dashboard.dataset_id:
        version_id = None  # outro dataset: passa a acompanhar a versão atual dele
    else:
        version_id = dashboard.version_id
    version = _target_version(db, ctx.workspace_id, dataset, version_id)
    filters = (
        data.filters
        if data.filters is not None
        else FilterSet.model_validate(dashboard.filters or {})
    )
    widgets = (
        data.widgets
        if data.widgets is not None
        else [
            WidgetIn(
                id=w.id,
                title=w.title,
                chart_type=w.chart_type,
                size=w.size,
                query=AggregateSpec.model_validate(w.config),
            )
            for w in dashboard.widgets
        ]
    )
    # Tudo é revalidado contra a versão resultante: trocar de versão ou de dataset não pode
    # deixar widgets apontando para colunas que não existem.
    _validate_dashboard(widgets, filters, schema_of(version), version.version_number)
    if data.name is not None:
        _ensure_unique_name(db, ctx.workspace_id, data.name, exclude=dashboard.id)
        dashboard.name = data.name
    if "description" in changed:
        dashboard.description = data.description
    dashboard.dataset_id = dataset.id
    dashboard.version_id = version_id
    dashboard.filters = filters.model_dump(mode="json")
    if data.widgets is not None:
        _replace_widgets(db, dashboard, data.widgets)
    dashboard.updated_by_id = ctx.user.id
    dashboard.updated_at = utcnow()
    audit.record(
        db,
        "dashboard.updated",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dashboard",
        entity_id=dashboard.id,
        details={"fields": sorted(changed), "widgets": len(widgets)},
        ip=ctx.ip,
    )
    _commit(db)
    return _out(db, dashboard)


def delete_dashboard(db: Session, ctx: RequestContext, dashboard_id: uuid.UUID) -> None:
    dashboard = _get(db, ctx.workspace_id, dashboard_id)
    audit.record(
        db,
        "dashboard.deleted",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dashboard",
        entity_id=dashboard.id,
        details={"widgets": len(dashboard.widgets)},
        ip=ctx.ip,
    )
    db.delete(dashboard)
    db.commit()


# ---------------------------------------------------------------- consulta


def query_widget(
    db: Session, workspace_id: uuid.UUID, dashboard_id: uuid.UUID, data: DashboardQuery
) -> WidgetResult:
    dashboard = _get(db, workspace_id, dashboard_id)
    widget = next((w for w in dashboard.widgets if w.id == data.widget_id), None)
    if widget is None:
        raise NotFound("Widget não encontrado neste dashboard.")
    dataset = repo.get_dataset(db, workspace_id, dashboard.dataset_id)
    version = _target_version(db, workspace_id, dataset, dashboard.version_id)
    schema = schema_of(version)
    # Filtros da tela: erros voltam como estão, citando a posição do filtro.
    screen = tuple(
        build_where(group.filters, group.match, None, schema, prefix=f"r{index}_")
        for index, group in enumerate(data.extra_filters)
    )
    try:
        saved = FilterSet.model_validate(dashboard.filters or {})
        general = build_where(
            saved.filters, saved.match, None, schema, prefix="d", label="Filtro do dashboard"
        )
        spec = AggregateSpec.model_validate(widget.config)
        result = run_on_version(version, spec, extra=(general, *screen))
    except ValidationFailed as exc:
        if exc.code in {"query_timeout", "too_many_points"}:
            raise
        # A versão atual mudou de esquema depois que o widget foi salvo.
        raise ValidationFailed(
            f"Este widget não é compatível com a versão {version.version_number}: "
            f"{exc.message} Edite o widget ou fixe a versão do dashboard.",
            code="widget_incompatible",
            details={"reason": exc.code, "version": version.version_number},
        ) from exc
    return WidgetResult(widget_id=widget.id, result=result)
