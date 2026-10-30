"""Aguarda o armazenamento de objetos ficar disponível e garante o bucket privado.

Executado como serviço único no Docker Compose antes de API e worker subirem.
"""

import logging
import sys
import time

from app.core.logging import configure_logging
from app.services import storage

logger = logging.getLogger("init_storage")


def main(attempts: int = 60, delay: float = 2.0) -> int:
    configure_logging()
    for attempt in range(1, attempts + 1):
        try:
            storage.ensure_bucket()
            logger.info("storage_ready", extra={"bucket": storage.bucket(), "attempt": attempt})
            return 0
        except storage.StorageError as exc:
            logger.info("storage_waiting", extra={"attempt": attempt, "error": type(exc).__name__})
            time.sleep(delay)
    logger.error("storage_unavailable")
    return 1


if __name__ == "__main__":
    sys.exit(main())
