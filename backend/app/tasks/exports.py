import uuid

from app.services.export_runner import TransientExportError, run_export
from app.tasks.celery_app import celery_app, settings


@celery_app.task(
    name="exports.run",
    autoretry_for=(TransientExportError,),
    retry_backoff=5,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=settings.job_max_attempts,
)
def run_export_task(export_id: str) -> str:
    return run_export(uuid.UUID(export_id))
