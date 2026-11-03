"""Auditoria consultável, exclusão controlada de datasets e versões, retenção de originais."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.db import session_scope
from app.models import DatasetVersion, ExportJob, ProcessingJob, Role, Upload
from app.models.base import utcnow
from app.services import storage
from app.services.export_runner import run_export
from app.services.job_runner import run_job
from app.services.retention_service import apply_retention
from tests.conftest import add_member, csrf, new_client, register
from tests.test_analytics import bi_dataset
from tests.test_transform_api import _apply, _create_set

PAID = [
    {
        "operation": "filter_rows",
        "conditions": [{"column": "status", "operator": "eq", "value": "pago"}],
    }
]


def _join(owner: dict[str, Any], role: Role) -> TestClient:
    other = new_client()
    member = register(other, workspace=f"Outro {role}")
    add_member(owner["workspace"]["id"], member["user"]["id"], role)
    other.post(
        "/api/v1/workspaces/switch",
        json={"workspace_id": owner["workspace"]["id"]},
        headers=csrf(other),
    )
    return other


def _two_versions(client: TestClient) -> tuple[str, str, str]:
    ds, v1 = bi_dataset(client)
    tset = _create_set(client, ds, rules=PAID).json()
    job = _apply(client, ds, v1, tset["id"]).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"
    v2 = client.get(f"/api/v1/datasets/{ds}").json()["current_version_id"]
    return ds, v1, v2


def _keys(s3: Any, prefix: str) -> list[str]:
    listed = s3.list_objects_v2(Bucket=storage.bucket(), Prefix=prefix)
    return [item["Key"] for item in listed.get("Contents", [])]


# ---------------------------------------------------------------- auditoria


def test_audit_is_searchable_by_admins_only(client: TestClient) -> None:
    owner = register(client)
    ds, _ = bi_dataset(client)
    client.post(
        "/api/v1/dashboards",
        json={
            "name": "Vendas",
            "dataset_id": ds,
            "widgets": [
                {
                    "title": "Total",
                    "chart_type": "kpi",
                    "query": {"metrics": [{"aggregation": "count"}]},
                }
            ],
        },
        headers=csrf(client),
    )
    everything = client.get("/api/v1/audit").json()
    actions = [e["action"] for e in everything["items"]]
    assert actions[0] == "dashboard.created"  # mais recente primeiro
    assert {"workspace.created", "dataset.upload", "import.requested"} <= set(actions)
    assert everything["items"][0]["actor_name"] == "Pessoa Teste"

    dashboards = client.get("/api/v1/audit", params={"action": "dashboard"}).json()
    assert [e["action"] for e in dashboards["items"]] == ["dashboard.created"]
    exact = client.get("/api/v1/audit", params={"action": "import.requested"}).json()
    assert exact["total"] == 1
    paged = client.get("/api/v1/audit", params={"page_size": 2}).json()
    assert (len(paged["items"]), paged["total"]) == (2, everything["total"])
    tomorrow = (utcnow() + timedelta(days=1)).date().isoformat()
    assert client.get("/api/v1/audit", params={"date_from": tomorrow}).json()["total"] == 0
    assert "dashboard.created" in client.get("/api/v1/audit/actions").json()
    assert client.get("/api/v1/audit", params={"action": "x'; DROP"}).status_code == 422

    analyst = _join(owner, Role.ANALYST)
    assert analyst.get("/api/v1/audit").status_code == 403
    stranger = new_client()
    register(stranger, workspace="Outra empresa")
    theirs = stranger.get("/api/v1/audit").json()
    assert all(
        e["action"] not in {"dashboard.created", "import.requested"} for e in theirs["items"]
    )


# ---------------------------------------------------------------- exclusão de dataset


def test_delete_dataset_shows_impact_and_requires_the_name(client: TestClient, s3: Any) -> None:
    owner = register(client)
    ds, v1, _v2 = _two_versions(client)
    client.post(
        "/api/v1/dashboards",
        json={
            "name": "Vendas",
            "dataset_id": ds,
            "version_id": v1,
            "widgets": [
                {
                    "title": "Total",
                    "chart_type": "kpi",
                    "query": {"metrics": [{"aggregation": "count"}]},
                }
            ],
        },
        headers=csrf(client),
    )
    export = client.post(
        "/api/v1/exports",
        json={"dataset_id": ds, "kind": "rows", "format": "csv"},
        headers=csrf(client),
    ).json()
    assert run_export(uuid.UUID(export["id"])) == "succeeded"
    prefix = f"workspaces/{owner['workspace']['id']}/"
    assert len(_keys(s3, prefix)) >= 5  # original, 2 versões (+ rejeitados), exportação

    impact = client.get(f"/api/v1/datasets/{ds}/deletion-impact").json()
    assert (impact["versions"], impact["uploads"], impact["jobs"], impact["exports"]) == (
        2,
        1,
        2,
        1,
    )
    assert [d["name"] for d in impact["dashboards"]] == ["Vendas"]
    assert impact["stored_bytes"] > 0
    assert impact["blocked_reason"] is None

    wrong = client.request(
        "DELETE", f"/api/v1/datasets/{ds}", json={"confirm_name": "outro"}, headers=csrf(client)
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "confirmation_mismatch"
    deleted = client.request(
        "DELETE", f"/api/v1/datasets/{ds}", json={"confirm_name": "vendas"}, headers=csrf(client)
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/datasets/{ds}").status_code == 404
    assert client.get("/api/v1/dashboards").json() == []
    assert client.get("/api/v1/exports").json()["items"] == []
    assert _keys(s3, prefix) == []  # nada sobra no armazenamento
    audit = client.get("/api/v1/audit", params={"action": "dataset.deleted"}).json()["items"][0]
    assert audit["details"] == {
        "versions": 2,
        "uploads": 1,
        "jobs": 2,
        "exports": 1,
        "stored_bytes": impact["stored_bytes"],
        "dashboards": 1,
    }


def test_delete_dataset_is_blocked_while_in_use_and_for_non_admins(client: TestClient) -> None:
    owner = register(client)
    ds, _ = bi_dataset(client)
    analyst = _join(owner, Role.ANALYST)
    assert analyst.get(f"/api/v1/datasets/{ds}/deletion-impact").status_code == 403
    assert (
        analyst.request(
            "DELETE",
            f"/api/v1/datasets/{ds}",
            json={"confirm_name": "vendas"},
            headers=csrf(analyst),
        ).status_code
        == 403
    )
    with session_scope() as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.dataset_id == uuid.UUID(ds)))
        assert job is not None
        job.status = "processing"
    blocked = client.request(
        "DELETE", f"/api/v1/datasets/{ds}", json={"confirm_name": "vendas"}, headers=csrf(client)
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "dataset_in_use"
    stranger = new_client()
    register(stranger, workspace="Outra")
    assert stranger.get(f"/api/v1/datasets/{ds}/deletion-impact").status_code == 404


# ---------------------------------------------------------------- exclusão de versão


def test_delete_versions_with_safeguards(client: TestClient, s3: Any) -> None:
    register(client)
    ds, v1, v2 = _two_versions(client)
    dashboard = client.post(
        "/api/v1/dashboards",
        json={
            "name": "Fixo",
            "dataset_id": ds,
            "version_id": v2,
            "widgets": [
                {
                    "title": "Total",
                    "chart_type": "kpi",
                    "query": {"metrics": [{"aggregation": "count"}]},
                }
            ],
        },
        headers=csrf(client),
    ).json()
    pinned = client.delete(f"/api/v1/datasets/{ds}/versions/{v2}", headers=csrf(client))
    assert pinned.status_code == 409
    assert "Fixo" in pinned.json()["error"]["message"]

    # A versão 1 é a origem da 2: some, e a linhagem da 2 perde a referência.
    with session_scope() as db:
        key = db.scalar(
            select(DatasetVersion.storage_key).where(DatasetVersion.id == uuid.UUID(v1))
        )
    assert key is not None
    impact = client.get(f"/api/v1/datasets/{ds}/versions/{v1}/deletion-impact").json()
    assert (impact["is_current"], impact["derived_versions"]) == (False, 1)
    assert (
        client.delete(f"/api/v1/datasets/{ds}/versions/{v1}", headers=csrf(client)).status_code
        == 204
    )
    with pytest.raises(ClientError):
        s3.head_object(Bucket=storage.bucket(), Key=key)
    versions = client.get(f"/api/v1/datasets/{ds}/versions").json()
    assert [(v["version_number"], v["parent_version_id"]) for v in versions] == [(2, None)]

    # Agora a 2 é a única: não pode sair sozinha.
    client.patch(
        f"/api/v1/dashboards/{dashboard['id']}", json={"version_id": None}, headers=csrf(client)
    )
    only = client.delete(f"/api/v1/datasets/{ds}/versions/{v2}", headers=csrf(client))
    assert only.status_code == 409
    assert "única versão" in only.json()["error"]["message"]


def test_deleting_the_current_version_promotes_the_previous(client: TestClient) -> None:
    register(client)
    ds, v1, v2 = _two_versions(client)
    impact = client.get(f"/api/v1/datasets/{ds}/versions/{v2}/deletion-impact").json()
    assert (impact["is_current"], impact["next_current_number"]) == (True, 1)
    assert (
        client.delete(f"/api/v1/datasets/{ds}/versions/{v2}", headers=csrf(client)).status_code
        == 204
    )
    detail = client.get(f"/api/v1/datasets/{ds}").json()
    assert detail["current_version_id"] == v1
    rows = client.get(f"/api/v1/datasets/{ds}/rows").json()
    assert rows["version_number"] == 1
    assert rows["total"] == 6
    with session_scope() as db:
        assert db.scalar(select(ExportJob.id)) is None


# ---------------------------------------------------------------- retenção


def test_retention_purges_old_originals_but_keeps_versions(client: TestClient, s3: Any) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    with session_scope() as db:
        upload = db.scalar(select(Upload).where(Upload.dataset_id == uuid.UUID(ds)))
        assert upload is not None
        key = upload.storage_key
        db.execute(
            update(Upload)
            .where(Upload.id == upload.id)
            .values(created_at=utcnow() - timedelta(days=40))
        )
    assert apply_retention()["purged"] == 0  # sem política, nada é apagado
    client.patch(
        "/api/v1/workspaces/current",
        json={"settings": {"original_retention_days": 30}},
        headers=csrf(client),
    )
    assert apply_retention()["purged"] == 1
    assert apply_retention()["purged"] == 0  # idempotente
    with pytest.raises(ClientError):
        s3.head_object(Bucket=storage.bucket(), Key=key)

    preview = client.get(f"/api/v1/datasets/{ds}/preview")
    assert preview.status_code == 410
    assert preview.json()["error"]["code"] == "original_purged"
    # As versões publicadas continuam consultáveis.
    assert client.get(f"/api/v1/datasets/{ds}/rows").json()["total"] == 6
    audit = client.get("/api/v1/audit", params={"action": "retention"}).json()["items"]
    assert audit[0]["details"]["retention_days"] == 30


def test_retention_keeps_recent_files_and_datasets_without_versions(client: TestClient) -> None:
    register(client)
    client.patch(
        "/api/v1/workspaces/current",
        json={"settings": {"original_retention_days": 7}},
        headers=csrf(client),
    )
    bi_dataset(client)  # recente: fica
    from tests.conftest import upload_csv
    from tests.test_analytics import BI_CSV

    draft = upload_csv(client, BI_CSV).json()["dataset"]  # sem versão publicada: fica
    with session_scope() as db:
        db.execute(
            update(Upload)
            .where(Upload.dataset_id == uuid.UUID(draft["id"]))
            .values(created_at=utcnow() - timedelta(days=40))
        )
    assert apply_retention()["purged"] == 0
