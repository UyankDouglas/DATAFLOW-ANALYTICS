import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import APIModel


class JobOut(APIModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    upload_id: uuid.UUID
    upload_filename: str | None = None
    kind: str
    status: str
    created_by_id: uuid.UUID | None
    created_by_name: str | None = None
    attempts: int
    max_attempts: int
    cancel_requested: bool = False
    bytes_total: int | None
    bytes_processed: int
    progress_percent: float | None = None
    rows_processed: int
    rows_total: int | None
    rows_valid: int | None
    rows_rejected: int | None
    error_code: str | None
    error_message: str | None
    warnings: list[Any]
    rejection_summary: dict[str, Any]
    metrics: dict[str, Any]
    config: dict[str, Any]
    rules_version: str
    result_version_id: uuid.UUID | None
    result_version_number: int | None = None
    queued_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OverviewResponse(BaseModel):
    datasets_total: int
    datasets_ready: int
    versions_total: int
    rows_published: int
    jobs_running: int
    jobs_failed_7d: int
    jobs_succeeded_7d: int
    rows_rejected_7d: int
    jobs_by_day: list[dict[str, Any]]
    recent_jobs: list[JobOut]
