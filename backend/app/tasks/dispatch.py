"""Publicação de tarefas pela API, sem importar o código pesado do worker."""

import logging
import uuid
from typing import Any

from kombu.exceptions import OperationalError as KombuOperationalError
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def _send(name: str, args: list[Any], task_id: str | None = None) -> bool:
    from app.tasks.celery_app import celery_app

    try:
        celery_app.send_task(name, args=args, task_id=task_id)
        return True
    except (KombuOperationalError, RedisError, OSError):
        # O job continua durável no PostgreSQL; a tarefa de recuperação o reenfileira.
        logger.warning("task_publish_failed", extra={"task": name})
        return False


def enqueue_import(job_id: uuid.UUID) -> bool:
    return _send("imports.run", [str(job_id)])


def enqueue_password_reset_email(email: str, token: str) -> bool:
    return _send("email.password_reset", [email, token])
