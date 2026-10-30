"""Acesso ao armazenamento de objetos compatível com S3 (MinIO).

O bucket é privado. Nenhuma URL pública é gerada: downloads passam pela API, que valida o
workspace antes de transmitir o conteúdo.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

_TRANSFER = TransferConfig(
    multipart_threshold=16 * 1024 * 1024, multipart_chunksize=16 * 1024 * 1024
)

StorageError = (BotoCoreError, ClientError)


@lru_cache
def get_s3() -> "S3Client":
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=60,
            signature_version="s3v4",
        ),
    )


def bucket() -> str:
    return get_settings().s3_bucket


def ensure_bucket() -> None:
    s3 = get_s3()
    try:
        s3.head_bucket(Bucket=bucket())
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in ("404", "NoSuchBucket", "NotFound"):
            raise
        s3.create_bucket(Bucket=bucket())
        logger.info("bucket_created", extra={"bucket": bucket()})


def upload_file(local_path: Path, key: str, content_type: str) -> None:
    get_s3().upload_file(
        str(local_path),
        bucket(),
        key,
        ExtraArgs={"ContentType": content_type},
        Config=_TRANSFER,
    )


def download_file(key: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    get_s3().download_file(bucket(), key, str(local_path), Config=_TRANSFER)


def read_range(key: str, length: int) -> bytes:
    """Lê apenas os primeiros `length` bytes do objeto (pré-visualização)."""
    response = get_s3().get_object(Bucket=bucket(), Key=key, Range=f"bytes=0-{length - 1}")
    return response["Body"].read()


def delete_prefix(prefix: str) -> int:
    s3 = get_s3()
    deleted = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket(), Prefix=prefix):
        objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        if objects:
            s3.delete_objects(Bucket=bucket(), Delete={"Objects": objects, "Quiet": True})  # type: ignore[typeddict-item]
            deleted += len(objects)
    return deleted


def is_available() -> bool:
    try:
        get_s3().head_bucket(Bucket=bucket())
        return True
    except StorageError:
        return False


# Chaves determinísticas: nunca usam o nome enviado pelo usuário.
def upload_key(workspace_id: object, upload_id: object) -> str:
    return f"workspaces/{workspace_id}/uploads/{upload_id}/original"


def version_prefix(workspace_id: object, dataset_id: object, job_id: object) -> str:
    return f"workspaces/{workspace_id}/datasets/{dataset_id}/versions/{job_id}/"
