import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.analytics.aggregate import AggregateSpec
from app.schemas.analytics import AggregateResponse, FilterSet

MAX_WIDGETS = 24

ChartType = Literal["kpi", "line", "bar", "bar_horizontal", "area", "pie", "donut", "table"]
WidgetSize = Literal["small", "medium", "large"]


def _clean_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("informe um nome")
    return cleaned


class WidgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Id de um widget já salvo neste dashboard (mantido ao reorganizar); vazio = novo.
    id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=120)
    chart_type: ChartType
    size: WidgetSize = "medium"
    query: AggregateSpec

    _title = field_validator("title")(_clean_text)


class DashboardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    dataset_id: uuid.UUID
    # Vazio = acompanhar a versão atual; preenchido = fixar a versão escolhida.
    version_id: uuid.UUID | None = None
    filters: FilterSet = Field(default_factory=FilterSet)
    widgets: list[WidgetIn] = Field(default_factory=list, max_length=MAX_WIDGETS)

    _name = field_validator("name")(_clean_text)


class DashboardPatch(BaseModel):
    """Alteração parcial. `widgets`, quando enviado, é a lista completa e na nova ordem."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    dataset_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    filters: FilterSet | None = None
    widgets: list[WidgetIn] | None = Field(default=None, max_length=MAX_WIDGETS)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return _clean_text(value) if value is not None else None


class WidgetOut(BaseModel):
    id: uuid.UUID
    position: int
    title: str
    chart_type: str
    size: str
    query: AggregateSpec


class DashboardSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    dataset_id: uuid.UUID
    dataset_name: str
    version_id: uuid.UUID | None
    version_number: int | None  # só quando a versão está fixada
    widget_count: int
    chart_types: list[str]
    updated_by_name: str | None
    updated_at: datetime


class DashboardOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    dataset_id: uuid.UUID
    dataset_name: str
    version_id: uuid.UUID | None
    version_number: int | None
    # Versão usada nas consultas agora: a fixada ou a atual do dataset.
    resolved_version_id: uuid.UUID | None
    resolved_version_number: int | None
    filters: FilterSet
    widgets: list[WidgetOut]
    created_by_name: str | None
    updated_by_name: str | None
    created_at: datetime
    updated_at: datetime


class DashboardQuery(BaseModel):
    """Consulta de um widget com os filtros escolhidos na tela, combinados com E aos salvos.
    Cada grupo tem o próprio E/OU (filtros rápidos e filtros avançados, por exemplo)."""

    model_config = ConfigDict(extra="forbid")
    widget_id: uuid.UUID
    extra_filters: list[FilterSet] = Field(default_factory=list, max_length=2)


class WidgetResult(BaseModel):
    widget_id: uuid.UUID
    result: AggregateResponse
