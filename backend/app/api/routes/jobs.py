import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_db, require
from app.core.permissions import Permission
from app.schemas.common import Page
from app.schemas.job import JobOut, OverviewResponse
from app.services import jobs_service

router = APIRouter(tags=["jobs"])

STATUS_PATTERN = "^(active|queued|validating|processing|saving|succeeded|failed|cancelled)$"


@router.get("/jobs", response_model=Page[JobOut])
def list_jobs(
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[str | None, Query(pattern=STATUS_PATTERN)] = None,
    dataset_id: uuid.UUID | None = None,
    ctx: RequestContext = Depends(require(Permission.JOBS_VIEW)),
    db: Session = Depends(get_db),
) -> Page[JobOut]:
    return jobs_service.list_jobs(
        db, ctx.workspace_id, page=page, page_size=page_size, status=status, dataset_id=dataset_id
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.JOBS_VIEW)),
    db: Session = Depends(get_db),
) -> JobOut:
    return jobs_service.get_job_out(db, ctx.workspace_id, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    job_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.JOBS_CANCEL)),
    db: Session = Depends(get_db),
) -> JobOut:
    return jobs_service.cancel_job(db, ctx, job_id)


@router.get("/overview", response_model=OverviewResponse, tags=["overview"])
def overview(
    ctx: RequestContext = Depends(require(Permission.DATASETS_VIEW)),
    db: Session = Depends(get_db),
) -> OverviewResponse:
    return jobs_service.overview(db, ctx.workspace_id)
