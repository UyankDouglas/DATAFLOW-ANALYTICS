"""Recebimento de arquivos em streaming, com limite aplicado durante a leitura.

O corpo da requisição é gravado em disco em blocos enquanto é inspecionado (hash, tamanho e,
no CSV, UTF-8 e assinatura binária). Nada é mantido inteiro em memória. Planilhas XLSX são
verificadas como contêiner (ZIP, criptografia, macros, limite de descompressão) e abertas em
modo somente leitura, sem executar fórmulas. Só depois de validado o arquivo segue para o
armazenamento privado com um nome interno aleatório.
"""

import hashlib
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
from app.processing.xlsx import inspect_xlsx
from app.repositories import datasets as repo
from app.schemas.dataset import SheetImportRequest
from app.services import audit, storage
from app.services.preview_service import ensure_original

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".csv": "csv", ".xlsx": "xlsx"}
CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
UNSUPPORTED_HINTS = {
    ".xls": "O formato XLS antigo não é aceito. Salve a planilha como .xlsx ou CSV UTF-8.",
    ".xlsm": "Planilhas com macros não são aceitas. Salve como .xlsx (sem macros) ou CSV UTF-8.",
    ".xlsb": "O formato XLSB não é aceito. Salve a planilha como .xlsx ou CSV UTF-8.",
}


def sanitize_filename(raw: str) -> str:
    name = unicodedata.normalize("NFC", raw).replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*').strip(" .")
    return name[:200] or "arquivo.csv"


def dataset_name_from(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    return " ".join(stem.split())[:160] or "Dataset sem nome"


def _size_limit(file_format: str) -> tuple[int, str]:
    settings = get_settings()
    if file_format == "xlsx":
        message = f"O arquivo excede o limite de {settings.max_xlsx_mb} MB para XLSX."
        return settings.max_xlsx_bytes, message
    return (
        settings.max_csv_bytes,
        f"O arquivo excede o limite de {settings.max_csv_mb} MB para CSV.",
    )


def check_upload_request(
    ctx: RequestContext, filename: str, content_length: int | None
) -> tuple[str, str]:
    """Validações baratas antes de ler qualquer byte do corpo. Retorna (nome seguro, formato)."""
    settings = get_settings()
    rate_limit.hit(
        "upload", str(ctx.user.id), limit=settings.upload_limit_per_min, window_seconds=60
    )
    safe_name = sanitize_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension in UNSUPPORTED_HINTS:
        raise UnsupportedMedia(UNSUPPORTED_HINTS[extension], code="unsupported_extension")
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedMedia("Envie um arquivo .csv ou .xlsx.", code="unsupported_extension")
    file_format = ALLOWED_EXTENSIONS[extension]
    max_bytes, message = _size_limit(file_format)
    if content_length is not None and content_length > max_bytes:
        raise PayloadTooLarge(message)
    return safe_name, file_format


async def spool_to_disk(
    stream: AsyncIterator[bytes], target: Path, file_format: str = "csv"
) -> tuple[dict[str, Any], int]:
    """Grava o corpo em disco inspecionando cada bloco. Aborta ao exceder o limite."""
    max_bytes, message = _size_limit(file_format)
    inspector = StreamInspector()
    digest = hashlib.sha256()
    size = 0
    started = time.perf_counter()
    async with await anyio.open_file(target, "wb") as handle:
        async for chunk in stream:
            if size + len(chunk) > max_bytes:
                raise PayloadTooLarge(message)
            size += len(chunk)
            if file_format == "xlsx":
                digest.update(chunk)
            else:
                inspector.feed(chunk)
            await handle.write(chunk)
    if file_format == "xlsx":
        if size == 0:
            raise FileRejected("O arquivo está vazio.", "empty_file")
        limits = get_settings().xlsx_limits
        workbook = await anyio.to_thread.run_sync(inspect_xlsx, target, limits)
        detection = {"sha256": digest.hexdigest(), "size_bytes": size, **workbook}
    else:
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


def initial_options(detection: dict[str, Any]) -> ParseOptions:
    """Opções de leitura sugeridas pela inspeção do arquivo recebido."""
    if detection.get("format") == "xlsx":
        return ParseOptions(sheet=detection["default_sheet"], header_row=detection["header_row"])
    return ParseOptions(
        encoding=detection["suggested_encoding"],
        delimiter=detection["delimiter"],
        decimal_separator=detection["decimal_separator"],
        thousands_separator=detection["thousands_separator"],
    )


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
    file_format = str(detection.get("format", "csv"))
    try:
        storage.upload_file(temp_path, key, CONTENT_TYPES[file_format])
    except storage.StorageError as exc:
        logger.exception("storage_upload_failed")
        raise ServiceUnavailable("Não foi possível armazenar o arquivo. Tente novamente.") from exc

    dataset = Dataset(
        workspace_id=ctx.workspace_id,
        name=(dataset_name or "").strip()[:160] or dataset_name_from(filename),
        status=DatasetStatus.DRAFT,
        source_format=file_format,
        created_by_id=ctx.user.id,
        parse_options=initial_options(detection).model_dump(),
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
        file_format=file_format,
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
        details={
            "upload_id": str(upload_id),
            "size_bytes": upload.size_bytes,
            "format": file_format,
        },
        ip=ctx.ip,
    )
    db.commit()
    logger.info(
        "upload_stored", extra={"upload_id": str(upload_id), "size_bytes": upload.size_bytes}
    )
    return dataset, upload


def import_sheet(
    db: Session, ctx: RequestContext, dataset_id: uuid.UUID, request: SheetImportRequest
) -> tuple[Dataset, Upload]:
    """Outra aba da mesma planilha vira um dataset independente (cópia do arquivo enviado)."""
    source = repo.get_dataset(db, ctx.workspace_id, dataset_id)
    upload = repo.latest_upload(db, source.id)
    if upload is None or upload.file_format != "xlsx":
        raise ValidationFailed("Somente planilhas XLSX têm abas.", code="not_xlsx")
    sheets = [s["name"] for s in upload.detection.get("sheets", [])]
    if request.sheet not in sheets:
        raise ValidationFailed(
            f"A aba '{request.sheet}' não existe na planilha.", code="xlsx_sheet_not_found"
        )
    ensure_original(upload)
    upload_id = uuid.uuid4()
    key = storage.upload_key(ctx.workspace_id, upload_id)
    try:
        storage.copy_object(upload.storage_key, key)
    except storage.StorageError as exc:
        logger.exception("storage_copy_failed")
        raise ServiceUnavailable("Não foi possível copiar a planilha. Tente novamente.") from exc

    name = (request.name or "").strip() or f"{source.name} - {request.sheet}"
    dataset = Dataset(
        workspace_id=ctx.workspace_id,
        name=name[:160],
        status=DatasetStatus.DRAFT,
        source_format="xlsx",
        created_by_id=ctx.user.id,
        parse_options=ParseOptions(sheet=request.sheet).model_dump(),
    )
    db.add(dataset)
    db.flush()
    copy = Upload(
        id=upload_id,
        workspace_id=ctx.workspace_id,
        dataset_id=dataset.id,
        uploaded_by_id=ctx.user.id,
        original_filename=upload.original_filename,
        storage_key=key,
        file_format="xlsx",
        size_bytes=upload.size_bytes,
        sha256=upload.sha256,
        detection={**upload.detection, "default_sheet": request.sheet},
        upload_ms=None,
    )
    db.add(copy)
    audit.record(
        db,
        "dataset.sheet_imported",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="dataset",
        entity_id=dataset.id,
        details={"source_dataset_id": str(source.id), "upload_id": str(upload_id)},
        ip=ctx.ip,
    )
    db.commit()
    return dataset, copy
