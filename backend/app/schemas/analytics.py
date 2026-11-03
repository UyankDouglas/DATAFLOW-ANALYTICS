import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.aggregate import AggregateSpec
from app.analytics.query import MAX_FILTERS
from app.processing.transforms import Condition


class FilterSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: list[Condition] = Field(default_factory=list, max_length=MAX_FILTERS)
    match: Literal["all", "any"] = "all"


class AnalyticsQuery(AggregateSpec):
    """Consulta analítica avulsa sobre uma versão (a atual, se `version_id` vier vazio)."""

    version_id: uuid.UUID | None = None
    # Grupos de filtros combinados com E aos da consulta, cada um com o próprio E/OU
    # (filtros gerais de um dashboard em edição, filtros escolhidos na tela).
    extra_filters: list[FilterSet] = Field(default_factory=list, max_length=2)


class _FromResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MetricInfo(_FromResult):
    key: str
    aggregation: str
    column: str | None
    label: str
    data_type: str  # tipo do resultado: integer, decimal, date, datetime
    scale: int | None


class DimensionInfo(_FromResult):
    column: str
    data_type: str
    granularity: str | None


class ComparisonInfo(_FromResult):
    column: str
    mode: str
    current_start: dt.date
    current_end: dt.date
    previous_start: dt.date
    previous_end: dt.date
    previous_rows: int


class GroupRow(_FromResult):
    key: Any  # valor da dimensão (nulo = sem valor); ausente nos KPIs
    values: list[Any]  # decimais como texto, para não perder precisão
    previous: list[Any] | None


class OthersRow(_FromResult):
    groups: int
    values: list[Any]
    previous: list[Any] | None


class AggregateResponse(_FromResult):
    version_id: uuid.UUID
    version_number: int
    metrics: list[MetricInfo]
    dimension: DimensionInfo | None
    rows: list[GroupRow]
    matched_rows: int
    total_groups: int | None
    others: OthersRow | None
    comparison: ComparisonInfo | None
    duration_ms: int
