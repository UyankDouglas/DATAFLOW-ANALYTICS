"""Limpeza de objetos órfãos: só apaga o que nada no banco referencia, depois da carência."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.db import session_scope
from app.models import DatasetVersion, ExportJob, JobStatus, ProcessingJob, Upload
from app.models.base import utcnow
from app.services import storage
from app.services.job_runner import run_job
from app.services.orphan_service import sweep_orphans
from tests.conftest import register
from tests.test_admin_api import PAID, _keys
from tests.test_analytics import bi_dataset
from tests.test_exports_api import PAID_BY_VALUE, _request, _run
from tests.test_transform_api import _apply, _create_set

LATER = timedelta(hours=25)  # além da carência padrão de 24 h


def _put(s3: Any, key: str, body: bytes = b"x") -> None:
    s3.put_object(Bucket=storage.bucket(), Key=key, Body=body)


def _exists(s3: Any, key: str) -> bool:
    try:
        s3.head_object(Bucket=storage.bucket(), Key=key)
    except ClientError:
        return False
    return True


def _random_upload_key(workspace_id: str) -> str:
    return storage.upload_key(workspace_id, uuid.uuid4())


def test_referenced_objects_stay_and_orphans_go(client: TestClient, s3: Any) -> None:
    owner = register(client)
    workspace = owner["workspace"]["id"]
    ds, _ = bi_dataset(client)
    kept = _keys(s3, "workspaces/")
    assert len(kept) == 2  # original enviado + Parquet da versão

    orphan_upload = _random_upload_key(workspace)
    orphan_version = storage.version_prefix(workspace, ds, uuid.uuid4()) + "data.parquet"
    orphan_export = storage.export_key(workspace, uuid.uuid4(), "csv")
    for key in (orphan_upload, orphan_version, orphan_export):
        _put(s3, key, b"12345")

    # Dentro da carência nada é apagado: o commit de um envio pode ainda estar a caminho.
    fresh = sweep_orphans()
    assert fresh["recent"] == 5
    assert fresh["removed"] == 0

    preview = sweep_orphans(now=utcnow() + LATER, dry_run=True)
    assert preview["orphans"] == 3
    assert preview["removed"] == 0
    assert all(_exists(s3, key) for key in (orphan_upload, orphan_version, orphan_export))

    stats = sweep_orphans(now=utcnow() + LATER)
    assert stats["scanned"] == 5
    assert stats["orphans"] == stats["removed"] == 3
    assert stats["bytes_removed"] == 15
    assert sorted(_keys(s3, "workspaces/")) == sorted(kept)
    # A versão continua consultável depois da varredura.
    assert client.get(f"/api/v1/datasets/{ds}/rows").json()["total"] == 6
    assert sweep_orphans(now=utcnow() + LATER)["removed"] == 0  # idempotente


def test_objects_of_work_in_progress_are_kept(client: TestClient, s3: Any) -> None:
    owner = register(client)
    workspace = owner["workspace"]["id"]
    ds, v1 = bi_dataset(client)
    tset = _create_set(client, ds, rules=PAID).json()
    job_id = _apply(client, ds, v1, tset["id"]).json()["id"]  # na fila, sem worker
    pending = storage.version_prefix(workspace, ds, job_id) + "data.parquet"
    _put(s3, pending)
    export = _request(client, ds, **PAID_BY_VALUE).json()  # na fila
    pending_export = storage.export_key(workspace, export["id"], "csv")
    _put(s3, pending_export)

    stats = sweep_orphans(now=utcnow() + LATER)
    assert stats["removed"] == 0
    assert _exists(s3, pending)
    assert _exists(s3, pending_export)

    # O job termina sem publicar: o objeto que ele deixou passa a ser órfão.
    with session_scope() as db:
        db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == uuid.UUID(job_id))
            .values(status=JobStatus.FAILED)
        )
    assert sweep_orphans(now=utcnow() + LATER)["removed"] == 1
    assert not _exists(s3, pending)
    assert _exists(s3, pending_export)


def test_published_version_and_finished_export_are_referenced(client: TestClient, s3: Any) -> None:
    register(client)
    ds, v1 = bi_dataset(client)
    tset = _create_set(client, ds, rules=PAID).json()
    job_id = _apply(client, ds, v1, tset["id"]).json()["id"]
    assert run_job(uuid.UUID(job_id)) == "succeeded"
    export_id = _request(client, ds, **PAID_BY_VALUE).json()["id"]
    assert _run(export_id) == "succeeded"
    before = sorted(_keys(s3, "workspaces/"))

    assert sweep_orphans(now=utcnow() + LATER)["removed"] == 0
    assert sorted(_keys(s3, "workspaces/")) == before

    # Expiração que limpou o banco mas não conseguiu apagar o arquivo: a varredura termina o serviço.
    with session_scope() as db:
        key = db.scalar(select(ExportJob.storage_key).where(ExportJob.id == uuid.UUID(export_id)))
        db.execute(
            update(ExportJob)
            .where(ExportJob.id == uuid.UUID(export_id))
            .values(status="expired", storage_key=None)
        )
    assert key
    assert _exists(s3, key)
    assert sweep_orphans(now=utcnow() + LATER)["removed"] == 1
    assert not _exists(s3, key)
    with session_scope() as db:
        assert db.scalar(
            select(DatasetVersion.id).where(DatasetVersion.job_id == uuid.UUID(job_id))
        )


def test_purged_original_left_behind_is_removed(client: TestClient, s3: Any) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    with session_scope() as db:
        upload = db.scalar(select(Upload).where(Upload.dataset_id == uuid.UUID(ds)))
        assert upload is not None
        key = upload.storage_key
        # Retenção marcou o original como expurgado, mas o objeto ficou para trás.
        upload.purged_at = utcnow()
    assert sweep_orphans(now=utcnow() + LATER)["removed"] == 1
    assert not _exists(s3, key)


def test_unknown_keys_are_never_deleted(client: TestClient, s3: Any) -> None:
    owner = register(client)
    workspace = owner["workspace"]["id"]
    unknown = [
        f"workspaces/{workspace}/notas.txt",
        f"workspaces/{workspace}/uploads/nao-e-uuid/original",
        storage.upload_key(workspace, uuid.uuid4()) + ".bak",
    ]
    for key in unknown:
        _put(s3, key)
    _put(s3, "backups/pg.dump")  # fora do prefixo da aplicação: nem é listado

    stats = sweep_orphans(now=utcnow() + LATER)
    assert stats["unknown"] == 3
    assert stats["removed"] == 0
    assert stats["scanned"] == 3
    assert all(_exists(s3, key) for key in [*unknown, "backups/pg.dump"])


def test_refused_deletes_are_counted(
    client: TestClient, s3: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = register(client)
    key = _random_upload_key(owner["workspace"]["id"])
    _put(s3, key)
    monkeypatch.setattr(storage, "delete_keys", lambda keys: list(keys))
    stats = sweep_orphans(now=utcnow() + LATER)
    assert stats["orphans"] == 1
    assert stats["failed"] == 1
    assert stats["removed"] == 0
    assert _exists(s3, key)


# ---------------------------------------------------------------- integridade após restauração


def test_verify_storage_finds_missing_and_altered_objects(client: TestClient, s3: Any) -> None:
    from app.scripts.verify_storage import verify

    register(client)
    ds, _ = bi_dataset(client)
    export_id = _request(client, ds, **PAID_BY_VALUE).json()["id"]
    assert _run(export_id) == "succeeded"
    clean = verify(deep=True)
    assert (clean["uploads"], clean["versions"], clean["exports"]) == (1, 1, 1)
    assert clean["hashes"] == 2
    assert clean["missing"] == []
    assert clean["mismatched"] == []

    with session_scope() as db:
        version = db.scalar(
            select(DatasetVersion).where(DatasetVersion.dataset_id == uuid.UUID(ds))
        )
        upload = db.scalar(select(Upload).where(Upload.dataset_id == uuid.UUID(ds)))
        assert version is not None
        assert upload is not None
    # Restauração inconsistente: o Parquet de outro ponto no tempo e o original perdido.
    body = s3.get_object(Bucket=storage.bucket(), Key=version.storage_key)["Body"].read()
    _put(s3, version.storage_key, body[::-1])
    s3.delete_object(Bucket=storage.bucket(), Key=upload.storage_key)
    broken = verify(deep=True)
    assert broken["missing"] == [f"upload:{upload.id}"]
    assert broken["mismatched"] == [f"versao:{version.id}:sha256"]
    assert verify(deep=False)["mismatched"] == []  # o tamanho é igual: só o hash percebe
