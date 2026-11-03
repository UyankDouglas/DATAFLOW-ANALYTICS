import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.processing.transforms import MAX_RULES, Rule
from app.processing.types import DataType


class TransformationSetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    rules: list[Rule] = Field(max_length=MAX_RULES)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("informe um nome")
        return cleaned


class TransformationSetOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    description: str | None
    revision: int
    rules: list[dict[str, Any]]
    created_by_name: str | None
    updated_by_name: str | None
    created_at: datetime
    updated_at: datetime


class ColumnOut(BaseModel):
    name: str
    data_type: DataType
    format: str | None = None
    scale: int | None = None


class TransformPreviewRequest(BaseModel):
    source_version_id: uuid.UUID | None = None  # padrão: versão atual
    rules: list[Rule] = Field(max_length=MAX_RULES)


class PreviewRow(BaseModel):
    row: int
    values: list[Any]


class ExcludedRow(BaseModel):
    row: int
    reason: str
    category: str
    column: str | None
    detail: str | None
    rule: int | None
    duplicate_of: int | None


class TransformPreviewResponse(BaseModel):
    source_version_id: uuid.UUID
    source_version_number: int
    source_row_count: int
    sample_size: int
    sample_is_complete: bool
    input_columns: list[ColumnOut]
    output_columns: list[ColumnOut]
    rows: list[PreviewRow]
    excluded: list[ExcludedRow]
    counts: dict[str, int | None]
    reasons: dict[str, int]


class DuplicateAnalysisRequest(BaseModel):
    columns: list[str] = Field(default_factory=list, max_length=500)  # vazio = todas
    keep: Literal["first", "last"] = "first"


class DuplicateGroup(BaseModel):
    key: list[Any]
    count: int
    kept_row: int
    sample_rows: list[int]


class DuplicateAnalysisResponse(BaseModel):
    version_id: uuid.UUID
    version_number: int
    columns: list[str]
    keep: Literal["first", "last"]
    total_rows: int
    distinct_keys: int
    duplicate_rows: int
    rows_after: int
    groups_with_duplicates: int
    top_groups: list[DuplicateGroup]


class TransformJobRequest(BaseModel):
    source_version_id: uuid.UUID
    transformation_set_id: uuid.UUID
