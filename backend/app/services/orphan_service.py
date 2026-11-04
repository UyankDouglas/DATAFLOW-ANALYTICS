"""Limpeza periódica de objetos órfãos no armazenamento.

Um objeto fica órfão quando o envio ao MinIO dá certo e o commit no PostgreSQL falha (upload,
publicação de versão, exportação), ou quando o banco é limpo e a remoção do objeto falha depois do
commit (exclusão de dataset ou versão, expiração de exportação, retenção). A varredura percorre o
bucket e apaga um objeto só quando todas as condições valem:

- a chave segue um dos formatos que o próprio sistema gera (qualquer outra é mantida e contada);
- nenhuma linha do banco aponta para ela: upload não expurgado, versão publicada (dados ou
  rejeitados) ou exportação;
- o processamento ou a exportação dono da chave não está em andamento;
- o objeto é mais antigo que a carência (`ORPHAN_GRACE_HOURS`, 24 h por padrão), maior que a
  duração máxima de uma tarefa, para nunca disputar com um envio cujo commit ainda vai acontecer.
"""

import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import session_scope
from app.models import (
    ACTIVE_EXPORT_STATUSES,
    TERMINAL_STATUSES,
    DatasetVersion,
    ExportJob,
    ProcessingJob,
    Upload,
)
from app.models.base import utcnow
from app.services import storage

logger = logging.getLogger(__name__)

ROOT = "workspaces/"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UPLOAD_KEY = re.compile(rf"^workspaces/{_UUID}/uploads/{_UUID}/original$")
VERSION_KEY = re.compile(
    rf"^workspaces/{_UUID}/datasets/{_UUID}/versions/(?P<job>{_UUID})/(data|rejected)\.parquet$"
)
EXPORT_KEY = re.compile(rf"^workspaces/{_UUID}/exports/(?P<export>{_UUID})/arquivo\.(csv|xlsx)$")


@dataclass
class SweepStats:
    scanned: int = 0
    recent: int = 0
    unknown: int = 0
    orphans: int = 0
    removed: int = 0
    failed: int = 0
    bytes_removed: int = 0


def _referenced(db: Session, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    found: set[str] = set(
        db.scalars(
            select(Upload.storage_key).where(
                Upload.storage_key.in_(keys), Upload.purged_at.is_(None)
            )
        )
    )
    for data_key, rejected_key in db.execute(
        select(DatasetVersion.storage_key, DatasetVersion.rejected_storage_key).where(
            or_(
                DatasetVersion.storage_key.in_(keys),
                DatasetVersion.rejected_storage_key.in_(keys),
            )
        )
    ):
        found.add(data_key)
        if rejected_key:
            found.add(rejected_key)
    found.update(
        key
        for key in db.scalars(select(ExportJob.storage_key).where(ExportJob.storage_key.in_(keys)))
        if key
    )
    return found


def _owners_in_progress(
    db: Session, job_ids: set[uuid.UUID], export_ids: set[uuid.UUID]
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    jobs: set[uuid.UUID] = set()
    exports: set[uuid.UUID] = set()
    if job_ids:
        jobs = set(
            db.scalars(
                select(ProcessingJob.id).where(
                    ProcessingJob.id.in_(job_ids), ProcessingJob.status.not_in(TERMINAL_STATUSES)
                )
            )
        )
    if export_ids:
        exports = set(
            db.scalars(
                select(ExportJob.id).where(
                    ExportJob.id.in_(export_ids), ExportJob.status.in_(ACTIVE_EXPORT_STATUSES)
                )
            )
        )
    return jobs, exports


def sweep_orphans(*, now: datetime | None = None, dry_run: bool = False) -> dict[str, int]:
    """Apaga os objetos órfãos do bucket. Com `dry_run`, só conta o que seria apagado."""
    now = now or utcnow()
    cutoff = now - timedelta(hours=get_settings().orphan_grace_hours)
    stats = SweepStats()
    for page in storage.list_objects(ROOT):
        stats.scanned += len(page)
        candidates: list[storage.StoredObject] = []
        job_of: dict[str, uuid.UUID] = {}
        export_of: dict[str, uuid.UUID] = {}
        for item in page:
            if item.last_modified >= cutoff:
                stats.recent += 1
                continue
            if version := VERSION_KEY.match(item.key):
                job_of[item.key] = uuid.UUID(version["job"])
            elif export := EXPORT_KEY.match(item.key):
                export_of[item.key] = uuid.UUID(export["export"])
            elif not UPLOAD_KEY.match(item.key):
                stats.unknown += 1
                continue
            candidates.append(item)
        if not candidates:
            continue
        with session_scope() as db:
            referenced = _referenced(db, [item.key for item in candidates])
            busy_jobs, busy_exports = _owners_in_progress(
                db, set(job_of.values()), set(export_of.values())
            )
        orphans = [
            item
            for item in candidates
            if item.key not in referenced
            and job_of.get(item.key) not in busy_jobs
            and export_of.get(item.key) not in busy_exports
        ]
        stats.orphans += len(orphans)
        if dry_run or not orphans:
            continue
        try:
            refused = set(storage.delete_keys([item.key for item in orphans]))
        except storage.StorageError:
            logger.warning("orphan_delete_failed", extra={"count": len(orphans)})
            stats.failed += len(orphans)
            continue
        for item in orphans:
            if item.key in refused:
                stats.failed += 1
                continue
            stats.removed += 1
            stats.bytes_removed += item.size
            # As chaves só têm identificadores gerados pelo sistema, nunca texto do usuário.
            logger.debug("orphan_removed", extra={"key": item.key})
    if stats.orphans or stats.unknown or stats.failed:
        logger.info("orphans_swept", extra={**asdict(stats), "dry_run": dry_run})
    return asdict(stats)
