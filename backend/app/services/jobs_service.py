import uuid
from datetime import timedelta

from sqlalchemy import Select, case, func, select, update
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.errors import Conflict
from app.models import (
    RUNNING_STATUSES,
    TERMINAL_STATUSES,
    Dataset,
    DatasetStatus,
    DatasetVersion,
    JobStatus,
    ProcessingJob,
    Upload,
    User,
)
from app.models.base import utcnow
from app.repositories import datasets as repo
from app.schemas.common import Page
from app.schemas.job import JobOut, OverviewResponse
from app.services import audit


def _query() -> Select[ProcessingJob, str, str, str, int]:
    return (
        select(
            ProcessingJob,
            Dataset.name,
            Upload.original_filename,
            User.full_name,
            DatasetVersion.version_number,
        )
        .join(Dataset, Dataset.id == ProcessingJob.dataset_id)
        .join(Upload, Upload.id == ProcessingJob.upload_id)
        .outerjoin(User, User.id == ProcessingJob.created_by_id)
        .outerjoin(DatasetVersion, DatasetVersion.id == ProcessingJob.result_version_id)
    )


def to_out(
    job: ProcessingJob,
    dataset_name: str | None,
    filename: str | None,
    user_name: str | None,
    version_number: int | None,
) -> JobOut:
    out = JobOut.model_validate(job)
    out.dataset_name = dataset_name
    out.upload_filename = filename
    out.created_by_name = user_name
    out.result_version_number = version_number
    out.cancel_requested = job.cancel_requested_at is not None
    if job.status == JobStatus.SUCCEEDED:
        out.progress_percent = 100.0
    elif job.bytes_total and job.status in RUNNING_STATUSES and job.bytes_processed:
        out.progress_percent = round(min(job.bytes_processed / job.bytes_total, 1.0) * 100, 1)
    return out


def get_job_out(db: Session, workspace_id: uuid.UUID, job_id: uuid.UUID) -> JobOut:
    repo.get_job(db, workspace_id, job_id)
    row = db.execute(_query().where(ProcessingJob.id == job_id)).one()
    return to_out(*row)


def list_jobs(
    db: Session,
    workspace_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
    status: str | None,
    dataset_id: uuid.UUID | None,
) -> Page[JobOut]:
    filters = [ProcessingJob.workspace_id == workspace_id]
    if status == "active":
        filters.append(ProcessingJob.status.in_([JobStatus.QUEUED, *RUNNING_STATUSES]))
    elif status:
        filters.append(ProcessingJob.status == status)
    if dataset_id:
        filters.append(ProcessingJob.dataset_id == dataset_id)
    total = db.scalar(select(func.count()).select_from(ProcessingJob).where(*filters)) or 0
    rows = db.execute(
        _query()
        .where(*filters)
        .order_by(ProcessingJob.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return Page[JobOut](
        items=[to_out(*row) for row in rows], total=total, page=page, page_size=page_size
    )


def cancel_job(db: Session, ctx: RequestContext, job_id: uuid.UUID) -> JobOut:
    job = repo.get_job(db, ctx.workspace_id, job_id)
    if job.status in TERMINAL_STATUSES:
        raise Conflict("Este processamento já foi finalizado.", code="job_finished")
    now = utcnow()
    # Job ainda na fila: cancela atomicamente se nenhum worker o reivindicou.
    result = db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job.id, ProcessingJob.status == JobStatus.QUEUED)
        .values(status=JobStatus.CANCELLED, cancel_requested_at=now, finished_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount:  # type: ignore[attr-defined]
        dataset = db.get(Dataset, job.dataset_id)
        if dataset is not None:
            dataset.status = (
                DatasetStatus.READY if dataset.current_version_id else DatasetStatus.DRAFT
            )
    else:
        # Em execução: cancelamento cooperativo; o worker confirma ao parar.
        db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job.id, ProcessingJob.cancel_requested_at.is_(None))
            .values(cancel_requested_at=now)
            .execution_options(synchronize_session=False)
        )
    audit.record(
        db,
        "job.cancel_requested",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="job",
        entity_id=job.id,
        ip=ctx.ip,
    )
    db.commit()
    db.expire_all()
    return get_job_out(db, ctx.workspace_id, job.id)


def overview(db: Session, workspace_id: uuid.UUID) -> OverviewResponse:
    since = utcnow() - timedelta(days=7)
    datasets_total, datasets_ready = db.execute(
        select(func.count(), func.count().filter(Dataset.status == DatasetStatus.READY)).where(
            Dataset.workspace_id == workspace_id
        )
    ).one()
    versions_total = (
        db.scalar(
            select(func.count())
            .select_from(DatasetVersion)
            .where(DatasetVersion.workspace_id == workspace_id)
        )
        or 0
    )
    rows_published = (
        db.scalar(
            select(func.coalesce(func.sum(DatasetVersion.row_count), 0))
            .join(Dataset, Dataset.current_version_id == DatasetVersion.id)
            .where(Dataset.workspace_id == workspace_id)
        )
        or 0
    )
    jobs = db.execute(
        select(
            func.count().filter(ProcessingJob.status.in_([JobStatus.QUEUED, *RUNNING_STATUSES])),
            func.count().filter(
                ProcessingJob.status == JobStatus.FAILED, ProcessingJob.created_at >= since
            ),
            func.count().filter(
                ProcessingJob.status == JobStatus.SUCCEEDED, ProcessingJob.created_at >= since
            ),
            func.coalesce(
                func.sum(
                    case((ProcessingJob.created_at >= since, ProcessingJob.rows_rejected), else_=0)
                ),
                0,
            ),
        ).where(ProcessingJob.workspace_id == workspace_id)
    ).one()

    window = utcnow() - timedelta(days=14)
    recent_rows = db.execute(
        select(ProcessingJob.created_at, ProcessingJob.status, ProcessingJob.rows_total).where(
            ProcessingJob.workspace_id == workspace_id, ProcessingJob.created_at >= window
        )
    ).all()
    by_day: dict[str, dict[str, int]] = {}
    for offset in range(14):
        day = (utcnow() - timedelta(days=13 - offset)).date().isoformat()
        by_day[day] = {"succeeded": 0, "failed": 0, "other": 0, "rows": 0}
    for created_at, status, rows_total in recent_rows:
        bucket = by_day.get(created_at.date().isoformat())
        if bucket is None:
            continue
        key = status if status in ("succeeded", "failed") else "other"
        bucket[key] += 1
        bucket["rows"] += int(rows_total or 0)

    recent = db.execute(
        _query()
        .where(ProcessingJob.workspace_id == workspace_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(6)
    ).all()
    return OverviewResponse(
        datasets_total=datasets_total,
        datasets_ready=datasets_ready,
        versions_total=versions_total,
        rows_published=int(rows_published),
        jobs_running=jobs[0],
        jobs_failed_7d=jobs[1],
        jobs_succeeded_7d=jobs[2],
        rows_rejected_7d=int(jobs[3]),
        jobs_by_day=[{"date": day, **values} for day, values in by_day.items()],
        recent_jobs=[to_out(*row) for row in recent],
    )
