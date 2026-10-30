from app.services.job_runner import cleanup_work_dir, recover_jobs
from app.tasks.celery_app import celery_app


@celery_app.task(name="maintenance.recover_jobs")
def recover_jobs_task() -> dict[str, int]:
    return recover_jobs()


@celery_app.task(name="maintenance.cleanup_work_dir")
def cleanup_work_dir_task() -> int:
    return cleanup_work_dir()
