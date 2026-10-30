"""Aplicação Celery compartilhada pelo worker e pelo beat.

O estado de cada job vive no PostgreSQL; o Celery é apenas o transporte. Por isso não há
backend de resultados e as tarefas são idempotentes (reivindicação condicional do job).
"""

from celery import Celery
from celery.signals import worker_process_init, worker_ready

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

celery_app = Celery(
    "dataflow",
    broker=settings.redis_url,
    include=["app.tasks.imports", "app.tasks.maintenance", "app.tasks.email"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
    # Confirmação tardia: seguro porque a tarefa reivindica o job de forma condicional e
    # uma reentrega de job já concluído vira no-op.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_soft_time_limit=3600,
    task_time_limit=3900,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 4200},
    task_default_queue="default",
    task_routes={"imports.*": {"queue": "imports"}},
    beat_schedule={
        "recover-jobs": {"task": "maintenance.recover_jobs", "schedule": 60.0},
        "cleanup-work-dir": {"task": "maintenance.cleanup_work_dir", "schedule": 3600.0},
    },
)


@worker_process_init.connect
def _init_worker_process(**_: object) -> None:
    configure_logging(get_settings().log_level)


@worker_ready.connect
def _recover_on_start(**_: object) -> None:
    # Recupera jobs órfãos de um worker anterior assim que este worker fica pronto.
    celery_app.send_task("maintenance.recover_jobs")
