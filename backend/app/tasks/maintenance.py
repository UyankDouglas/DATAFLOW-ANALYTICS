from app.services.export_runner import expire_exports, recover_exports
from app.services.job_runner import cleanup_work_dir, recover_jobs
from app.services.orphan_service import sweep_orphans
from app.services.retention_service import apply_retention
from app.tasks.celery_app import celery_app


@celery_app.task(name="maintenance.recover_jobs")
def recover_jobs_task() -> dict[str, int]:
    return recover_jobs()


@celery_app.task(name="maintenance.cleanup_work_dir")
def cleanup_work_dir_task() -> int:
    return cleanup_work_dir()


@celery_app.task(name="maintenance.recover_exports")
def recover_exports_task() -> dict[str, int]:
    return recover_exports()


@celery_app.task(name="maintenance.expire_exports")
def expire_exports_task() -> int:
    return expire_exports()


@celery_app.task(name="maintenance.apply_retention")
def apply_retention_task() -> dict[str, int]:
    return apply_retention()


@celery_app.task(name="maintenance.sweep_orphans")
def sweep_orphans_task() -> dict[str, int]:
    return sweep_orphans()
