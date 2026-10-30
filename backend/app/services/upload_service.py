"""Recebimento de arquivos em streaming, com limite aplicado durante a leitura.

O corpo da requisição é gravado em disco em blocos enquanto é inspecionado (hash, tamanho,
UTF-8, assinatura binária). Nada é mantido inteiro em memória. Só depois de validado o arquivo
segue para o armazenamento privado com um nome interno aleatório.
"""

import logging
import time
import unicodedata
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import anyio
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import PayloadTooLarge, ServiceUnavailable, UnsupportedMedia, ValidationFailed
from app.models import Dataset, DatasetStatus, Upload
from app.processing.inspection import FileRejected, StreamInspector
from app.processing.types import ParseOptions
from app.services import audit, storage

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".csv": "csv"}
FUTURE_EXTENSIONS = {".xlsx"}  # suporte real chega na Fase 2


def sanitize_filename(raw: str) -> str:
    name = unicodedata.normalize("NFC", raw).replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*').strip(" .")
    return name[:200] or "arquivo.csv"


def dataset_name_from(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    return " ".join(stem.split())[:160] or "Dataset sem nome"


def check_upload_request(ctx: RequestContext, filename: str, content_length: int | None) -> str:
    """Validações baratas antes de ler qualquer byte do corpo."""
    settings = get_settings()
    rate_limit.hit(
        "upload", str(ctx.user.id), limit=settings.upload_limit_per_min, window_seconds=60
    )
    safe_name = sanitize_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension in FUTURE_EXTENSIONS:
        raise UnsupportedMedia(
            "Arquivos XLSX serão aceitos na próxima fase. Exporte a planilha como CSV UTF-8.",
            code="format_not_yet_supported",
        )
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedMedia("Envie um arquivo .csv.", code="unsupported_extension")
    if content_length is not None and content_length > settings.max_csv_bytes:
        raise PayloadTooLarge(f"O arquivo excede o limite de {settings.max_csv_mb} MB para CSV.")
    return safe_name


async def spool_to_disk(stream: AsyncIterator[bytes], target: Path) -> tuple[dict[str, Any], int]:
    """Grava o corpo em disco inspecionando cada bloco. Aborta ao exceder o limite."""
    settings = get_settings()
    max_bytes = settings.max_csv_bytes
    inspector = StreamInspector()
    started = time.perf_counter()
    async with await anyio.open_file(target, "wb") as handle:
        async for chunk in stream:
            if inspector.size + len(chunk) > max_bytes:
                raise PayloadTooLarge(
                    f"O arquivo excede o limite de {settings.max_csv_mb} MB para CSV."
                )
            inspector.feed(chunk)
            await handle.write(chunk)
    detection = inspector.finish()
    return detection, int((time.perf_counter() - started) * 1000)


def record_rejection(
    db: Session, ctx: RequestContext, exc: FileRejected, filename: str
) -> ValidationFailed:
    audit.record(
        db,
        "dataset.upload_rejected",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        details={"reason": exc.code, "extension": Path(filename).suffix.lower()},
        ip=ctx.ip,
    )
    db.commit()
    return ValidationFailed(str(exc), code=exc.code)


def store_upload(
    db: Session,
    ctx: RequestContext,
    *,
    upload_id: uuid.UUID,
    temp_path: Path,
    filename: str,
    detection: dict[str, Any],
    upload_ms: int,
    dataset_name: str | None,
) -> tuple[Dataset, Upload]:
    """Envia o arquivo validado ao armazenamento e registra os metadados (executa em thread)."""
    key = storage.upload_key(ctx.workspace_id, upload_id)
    try:
        storage.upload_file(temp_path, key, "text/csv")
    except storage.StorageError as exc:
        logger.exception("storage_upload_failed")
        raise ServiceUnavailable("Não foi possível armazenar o arquivo. Tente novamente.") from exc

    dataset = Dataset(
        workspace_id=ctx.workspace_id,
        name=(dataset_name or "").strip()[:160] or dataset_name_from(filename),
        status=DatasetStatus.DRAFT,
        source_format="csv",
        created_by_id=ctx.user.id,
        parse_options=ParseOptions(
            encoding=detection["suggested_encoding"],
            delimiter=detection["delimiter"],
            decimal_separator=detection["decimal_separator"],
            thousands_separator=detection["thousands_separator"],
        ).model_dump(),
    )
    db.add(dataset)
    db.flush()
    upload = Upload(
        id=upload_id,
        workspace_id=ctx.workspace_id,
        dataset_id=dataset.id,
        uploaded_by_id=ctx.user.id,
        original_filename=filename,
        storage_key=key,
        file_format="csv",
        size_bytes=detection["size_bytes"],
        sha256=detection["sha256"],
        detection={k: v for k, v in detection.items() if k not in ("sha256", "size_bytes")},
        upload_ms=upload_ms,
    )
    db.add(upload)
    audit.record(
        db,
        "dataset.upload",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dataset",
        entity_id=dataset.id,
        details={"upload_id": str(upload_id), "size_bytes": upload.size_bytes, "format": "csv"},
        ip=ctx.ip,
    )
    db.commit()
    logger.info(
        "upload_stored", extra={"upload_id": str(upload_id), "size_bytes": upload.size_bytes}
    )
    return dataset, upload
