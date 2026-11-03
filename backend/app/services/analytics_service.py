"""Consultas analíticas sobre versões publicadas (KPIs, agrupamentos, séries e comparações).

A autorização vem antes de qualquer leitura: a versão é buscada pelo workspace do contexto, e
só então o Parquet é baixado (ou lido do cache) e consultado com o DuckDB isolado.
"""

import uuid

import duckdb
from sqlalchemy.orm import Session

from app.analytics.aggregate import AggregateSpec, plan_aggregate, run_aggregate
from app.analytics.cache import local_parquet
from app.analytics.query import WhereClause, build_where
from app.core.errors import ServiceUnavailable
from app.models import DatasetVersion
from app.processing.types import ColumnSpec
from app.repositories import datasets as repo
from app.schemas.analytics import AggregateResponse, AnalyticsQuery


def schema_of(version: DatasetVersion) -> list[ColumnSpec]:
    return [ColumnSpec.model_validate(c) for c in version.column_schema]


def run_on_version(
    version: DatasetVersion, spec: AggregateSpec, *, extra: tuple[WhereClause, ...] = ()
) -> AggregateResponse:
    plan = plan_aggregate(spec, schema_of(version), extra=extra)
    path = local_parquet(f"v-{version.id}", version.storage_key, version.checksum_sha256)
    try:
        result = run_aggregate(path, plan)
    except duckdb.Error as exc:
        raise ServiceUnavailable("Não foi possível calcular os indicadores agora.") from exc
    return AggregateResponse.model_validate(
        {**vars(result), "version_id": version.id, "version_number": version.version_number}
    )


def query(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, data: AnalyticsQuery
) -> AggregateResponse:
    version = repo.resolve_version(db, workspace_id, dataset_id, data.version_id)
    spec = AggregateSpec.model_validate(data.model_dump(exclude={"version_id", "extra_filters"}))
    schema = schema_of(version)
    extra = tuple(
        build_where(group.filters, group.match, None, schema, prefix=f"x{index}_")
        for index, group in enumerate(data.extra_filters)
    )
    return run_on_version(version, spec, extra=extra)
