import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.processing.transforms import Condition

Category = Literal["rejeitado", "filtrado", "duplicado"]


class QualityIssueOut(BaseModel):
    category: Category
    reason: str
    column: str | None
    rule: int | None
    rule_label: str
    count: int
    example_row: int | None


class QualityReportOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    version_id: uuid.UUID
    version_number: int
    formula_version: str
    score: float | None
    metrics: dict[str, Any]
    issues: list[QualityIssueOut]
    computed_by_name: str | None
    computed_at: datetime
    duration_ms: int


class QualityVersionSummary(BaseModel):
    """Linha da comparação entre versões; `score` nulo com `computed` falso = sem relatório."""

    version_id: uuid.UUID
    version_number: int
    parent_version_number: int | None
    kind: str
    created_at: datetime
    computed: bool
    score: float | None = None
    indicators: dict[str, Any] = Field(default_factory=dict)
    components: dict[str, Any] = Field(default_factory=dict)


class InconsistencyRow(BaseModel):
    row: int
    line: int | None
    category: Category
    reason: str
    column: str | None
    original_value: str | None
    rule: int | None
    rule_label: str
    treatment: str
    detail: str | None
    duplicate_of: int | None
    record: dict[str, str | None]


class InconsistencyPage(BaseModel):
    version_id: uuid.UUID
    items: list[InconsistencyRow]
    total: int
    page: int
    page_size: int


class ValueCount(BaseModel):
    value: Any
    count: int


class ValueFrequency(BaseModel):
    column: str
    data_type: str
    total: int
    nulls: int
    distinct: int
    values: list[ValueCount]
    others: int  # registros com valores fora da lista


class RowsQuery(BaseModel):
    """Consulta do Data Explorer. Filtros usam os mesmos operadores das regras de filtro."""

    version_id: uuid.UUID | None = None
    page: int = Field(default=1, ge=1, le=100_000)
    page_size: int = Field(default=50, ge=1, le=200)
    sort: str | None = Field(default=None, max_length=63)
    direction: Literal["asc", "desc"] = "asc"
    columns: list[str] | None = Field(default=None, max_length=500)
    filters: list[Condition] = Field(default_factory=list, max_length=20)
    match: Literal["all", "any"] = "all"
    search: str | None = Field(default=None, max_length=100)
