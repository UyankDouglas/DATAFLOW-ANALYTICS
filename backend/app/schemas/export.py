import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.aggregate import AggregateSpec
from app.analytics.query import MAX_FILTERS
from app.processing.transforms import Condition
from app.schemas.analytics import FilterSet

ExportKind = Literal["rows", "report"]
ExportFormat = Literal["csv", "xlsx"]
CsvStyle = Literal["padrao", "excel_br"]


class RowsExport(BaseModel):
    """Mesma consulta do Data Explorer: filtros, busca, colunas e ordenação."""

    model_config = ConfigDict(extra="forbid")
    filters: list[Condition] = Field(default_factory=list, max_length=MAX_FILTERS)
    match: Literal["all", "any"] = "all"
    search: str | None = Field(default=None, max_length=100)
    columns: list[str] | None = Field(default=None, max_length=500)
    sort: str | None = Field(default=None, max_length=63)
    direction: Literal["asc", "desc"] = "asc"
    # Grupos de filtros da tela (rápidos e avançados), combinados com E aos de cima.
    extra_filters: list[FilterSet] = Field(default_factory=list, max_length=2)


class ReportQuery(AggregateSpec):
    """Consulta de um relatório: a mesma das análises, com mais grupos para o arquivo."""

    limit: int = Field(default=1000, ge=1, le=10_000)
    extra_filters: list[FilterSet] = Field(default_factory=list, max_length=2)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None  # vazio = versão atual no momento do pedido
    kind: ExportKind
    format: ExportFormat
    csv_style: CsvStyle = "excel_br"
    rows: RowsExport | None = None
    report: ReportQuery | None = None

    @model_validator(mode="after")
    def _matching_payload(self) -> "ExportRequest":
        if self.kind == "rows":
            if self.report is not None:
                raise ValueError("exportação de registros não leva consulta de relatório")
            self.rows = self.rows or RowsExport()
        elif self.report is None:
            raise ValueError("informe a consulta do relatório")
        elif self.rows is not None:
            raise ValueError("exportação de relatório não leva filtros de registros")
        return self


class ExportOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str
    version_id: uuid.UUID
    version_number: int
    kind: ExportKind
    format: ExportFormat
    status: str
    file_name: str
    params: dict[str, Any]
    estimated_rows: int | None
    row_count: int | None
    size_bytes: int | None
    error_code: str | None
    error_message: str | None
    created_by_name: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    duration_ms: int | None
    download_count: int
