import uuid

from pydantic import BaseModel, ConfigDict, Field


class DashboardRef(BaseModel):
    id: uuid.UUID
    name: str


class DatasetImpact(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    versions: int
    uploads: int
    jobs: int
    exports: int
    stored_bytes: int
    dashboards: list[DashboardRef]
    blocked_reason: str | None


class VersionImpact(BaseModel):
    version_id: uuid.UUID
    version_number: int
    is_current: bool
    next_current_number: int | None
    derived_versions: int
    exports: int
    stored_bytes: int
    pinned_by: list[DashboardRef]
    blocked_reason: str | None


class DeleteDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # O nome do dataset, digitado pela pessoa, confirma que ela sabe o que está apagando.
    confirm_name: str = Field(min_length=1, max_length=160)
