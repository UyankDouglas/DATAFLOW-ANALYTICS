import uuid

from app.services.job_runner import TransientJobError, run_import_job
from app.tasks.celery_app import celery_app, settings


@celery_app.task(
    name="imports.run",
    autoretry_for=(TransientJobError,),
    retry_backoff=5,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=settings.job_max_attempts,
)
def run_import(job_id: str) -> str:
    return run_import_job(uuid.UUID(job_id))
