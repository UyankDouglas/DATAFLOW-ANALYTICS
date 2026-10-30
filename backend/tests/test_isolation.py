"""Isolamento entre workspaces e RBAC: acesso por ID nunca atravessa workspaces."""

import uuid

from fastapi.testclient import TestClient

from app.models import Role
from app.services.job_runner import run_import_job
from tests.conftest import SALES_CSV, csrf, new_client, register, upload_csv
from tests.test_import_flow import import_payload


def _setup_owner_with_processed_dataset(client: TestClient) -> dict:
    register(client, workspace="Empresa A")
    dataset = upload_csv(client, SALES_CSV).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    job = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        json=import_payload(preview),
        headers=csrf(client),
    ).json()
    assert run_import_job(uuid.UUID(job["id"])) == "succeeded"
    detail = client.get(f"/api/v1/datasets/{dataset['id']}").json()
    return {"dataset": dataset, "job": job, "version_id": detail["current_version_id"]}


def test_other_workspace_cannot_read_or_act_on_resources(client: TestClient) -> None:
    owned = _setup_owner_with_processed_dataset(client)
    ds, job, version = owned["dataset"]["id"], owned["job"]["id"], owned["version_id"]

    intruder = new_client()
    register(intruder, workspace="Empresa B")
    for path in (
        f"/api/v1/datasets/{ds}",
        f"/api/v1/datasets/{ds}/preview",
        f"/api/v1/datasets/{ds}/columns",
        f"/api/v1/datasets/{ds}/versions",
        f"/api/v1/datasets/{ds}/rows",
        f"/api/v1/datasets/{ds}/rows?version_id={version}",
        f"/api/v1/datasets/{ds}/versions/{version}/rejected",
        f"/api/v1/jobs/{job}",
    ):
        response = intruder.get(path)
        assert response.status_code == 404, path

    assert intruder.post(f"/api/v1/jobs/{job}/cancel", headers=csrf(intruder)).status_code == 404
    assert intruder.post(
        f"/api/v1/datasets/{ds}/imports",
        json={"parse_options": {}, "columns": []},
        headers=csrf(intruder),
    ).status_code in (404, 422)
    assert intruder.get("/api/v1/datasets").json()["total"] == 0
    assert intruder.get("/api/v1/jobs").json()["total"] == 0
    overview = intruder.get("/api/v1/overview").json()
    assert overview["datasets_total"] == 0
    assert overview["rows_published"] == 0


def test_version_of_another_dataset_is_not_reachable_by_id_swap(client: TestClient) -> None:
    first = _setup_owner_with_processed_dataset(client)
    second = upload_csv(client, SALES_CSV, "outro.csv").json()["dataset"]
    response = client.get(f"/api/v1/datasets/{second['id']}/rows?version_id={first['version_id']}")
    assert response.status_code == 404


def test_cannot_switch_to_foreign_workspace(client: TestClient) -> None:
    register(client, workspace="Empresa A")
    other = new_client()
    foreign = register(other, workspace="Empresa B")["workspace"]["id"]
    response = client.post(
        "/api/v1/workspaces/switch", json={"workspace_id": foreign}, headers=csrf(client)
    )
    assert response.status_code == 404
    assert client.get("/api/v1/auth/me").json()["workspace"]["name"] == "Empresa A"


def test_viewer_role_is_read_only(client: TestClient) -> None:
    from tests.conftest import add_member

    owner = register(client, workspace="Empresa A")
    viewer_client = new_client()
    viewer = register(viewer_client, workspace="Pessoal")
    add_member(owner["workspace"]["id"], viewer["user"]["id"], Role.VIEWER)
    switch = viewer_client.post(
        "/api/v1/workspaces/switch",
        json={"workspace_id": owner["workspace"]["id"]},
        headers=csrf(viewer_client),
    )
    assert switch.status_code == 200

    me = viewer_client.get("/api/v1/auth/me").json()
    assert me["workspace"]["role"] == "viewer"
    assert "datasets:upload" not in me["permissions"]
    assert upload_csv(viewer_client, SALES_CSV).status_code == 403
    assert viewer_client.get("/api/v1/datasets").status_code == 200
    assert viewer_client.get("/api/v1/workspaces/current/members").status_code == 403


def test_removed_member_loses_access_immediately(client: TestClient) -> None:
    from sqlalchemy import delete

    from app.core.db import session_scope
    from app.models import WorkspaceMember
    from tests.conftest import add_member

    owner = register(client, workspace="Empresa A")
    member_client = new_client()
    member = register(member_client, workspace="Pessoal")
    add_member(owner["workspace"]["id"], member["user"]["id"], Role.ANALYST)
    member_client.post(
        "/api/v1/workspaces/switch",
        json={"workspace_id": owner["workspace"]["id"]},
        headers=csrf(member_client),
    )
    assert member_client.get("/api/v1/datasets").status_code == 200

    with session_scope() as db:
        db.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.user_id == uuid.UUID(member["user"]["id"]),
                WorkspaceMember.workspace_id == uuid.UUID(owner["workspace"]["id"]),
            )
        )
    response = member_client.get("/api/v1/datasets")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_member"
