"""Cache local de arquivos Parquet de versões publicadas.

Versões publicadas são imutáveis, então o cache nunca fica inconsistente: a chave é o id da
versão e o arquivo é validado pelo SHA-256 registrado na publicação.
"""

import logging
import os
import threading
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import ServiceUnavailable
from app.processing.pipeline import file_sha256
from app.services import storage

logger = logging.getLogger(__name__)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def local_parquet(cache_key: str, storage_key: str, checksum: str | None = None) -> Path:
    settings = get_settings()
    target = settings.cache_dir / f"{cache_key}.parquet"
    if target.exists():
        os.utime(target)
        return target
    with _lock_for(cache_key):
        if target.exists():
            return target
        tmp = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
        try:
            storage.download_file(storage_key, tmp)
        except storage.StorageError as exc:
            tmp.unlink(missing_ok=True)
            raise ServiceUnavailable("Não foi possível ler os dados processados agora.") from exc
        if checksum and file_sha256(tmp) != checksum:
            tmp.unlink(missing_ok=True)
            raise ServiceUnavailable("Integridade do arquivo processado não confirmada.")
        tmp.replace(target)
    _evict_if_needed(settings.cache_dir, settings.cache_max_mb * 1024 * 1024)
    return target


def _evict_if_needed(directory: Path, max_bytes: int) -> None:
    files = sorted(directory.glob("*.parquet"), key=lambda p: p.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    now = time.time()
    for file in files:
        if total <= max_bytes:
            break
        if now - file.stat().st_mtime < 60:
            continue  # pode estar em uso por uma consulta recente
        total -= file.stat().st_size
        file.unlink(missing_ok=True)
        logger.info("cache_evicted", extra={"file": file.name})
