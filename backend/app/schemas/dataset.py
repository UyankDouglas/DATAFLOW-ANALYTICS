import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.processing.types import ColumnConfig, DataType, ParseOptions
from app.schemas.common import APIModel


class UploadOut(APIModel):
    id: uuid.UUID
    original_filename: str
    file_format: str
    size_bytes: int
    sha256: str
    detection: dict[str, Any]
    upload_ms: int | None
    created_at: datetime


class DatasetColumnOut(APIModel):
    position: int
    source_name: str
    name: str
    data_type: DataType
    inferred_type: DataType | None
    format: str | None


class DatasetVersionOut(APIModel):
    id: uuid.UUID
    version_number: int
    status: str
    job_id: uuid.UUID
    upload_id: uuid.UUID
    created_by_id: uuid.UUID | None
    created_by_name: str | None = None
    row_count: int
    rejected_count: int
    size_bytes: int
    column_schema: list[dict[str, Any]]
    reconciliation: dict[str, Any]
    rules_version: str
    created_at: datetime


class DatasetOut(APIModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    source_format: str
    current_version_id: uuid.UUID | None
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DatasetListItem(DatasetOut):
    current_version_number: int | None = None
    row_count: int | None = None
    latest_upload: UploadOut | None = None
    latest_job_id: uuid.UUID | None = None
    latest_job_status: str | None = None


class DatasetDetail(DatasetOut):
    parse_options: dict[str, Any]
    columns: list[DatasetColumnOut]
    latest_upload: UploadOut | None
    current_version: DatasetVersionOut | None


class UploadResponse(BaseModel):
    dataset: DatasetOut
    upload: UploadOut


class ColumnPreview(BaseModel):
    position: int
    source_name: str
    inferred_type: DataType
    format: str | None
    scale: int | None
    ambiguous_formats: list[str]
    null_count: int
    null_ratio: float
    distinct_count: int
    is_empty: bool
    warnings: list[str]


class RowCountInfo(BaseModel):
    value: int
    exact: bool
    method: str


class PreviewResponse(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    upload: UploadOut
    parse_options: ParseOptions
    suggested_options: ParseOptions
    header: list[str]
    rows: list[list[str]]
    columns: list[ColumnPreview]
    column_count: int
    row_count: RowCountInfo
    sample_rows_analyzed: int
    sample_truncated: bool
    ragged_rows_in_sample: int
    empty_rows_in_sample: int
    duplicate_header_names: list[str]
    warnings: list[str]
    saved_columns: list[DatasetColumnOut]


class ImportRequest(BaseModel):
    parse_options: ParseOptions
    columns: list[ColumnConfig] = Field(min_length=1, max_length=500)
    confirm_ambiguous_formats: bool = False


class RowsResponse(BaseModel):
    version_id: uuid.UUID
    version_number: int
    columns: list[dict[str, Any]]
    rows: list[list[Any]]
    total: int
    page: int
    page_size: int


class RejectedRowsResponse(BaseModel):
    version_id: uuid.UUID
    columns: list[str]
    rows: list[list[Any]]
    total: int
    page: int
    page_size: int
