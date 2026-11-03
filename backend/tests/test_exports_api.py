"""Exportações: pedido, geração no worker, download autorizado, limites, expiração e falhas."""

import io
import uuid
import zipfile
from datetime import timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import session_scope
from app.models import AuditLog, ExportJob, ExportStatus, Role
from app.models.base import utcnow
from app.services import export_runner, storage
from app.services.export_runner import TransientExportError, expire_exports, run_export
from app.services.job_runner import run_job
from tests.conftest import add_member, csrf, new_client, register, upload_csv
from tests.test_analytics import bi_dataset
from tests.test_dashboards_api import _viewer_of
from tests.test_import_flow import import_payload

PAID_BY_VALUE = {
    "kind": "rows",
    "format": "csv",
    "rows": {
        "filters": [{"column": "status", "operator": "eq", "value": "pago"}],
        "columns": ["vendedor", "valor"],
        "sort": "valor",
        "direction": "desc",
    },
}


def _request(client: TestClient, ds: str, **body: Any) -> Any:
    return client.post("/api/v1/exports", json={"dataset_id": ds, **body}, headers=csrf(client))


def _run(export_id: str) -> str:
    return run_export(uuid.UUID(export_id))


def _actions(workspace_id: str) -> list[str]:
    with session_scope() as db:
        return list(
            db.scalars(
                select(AuditLog.action)
                .where(
                    AuditLog.workspace_id == uuid.UUID(workspace_id),
                    AuditLog.entity_type == "export",
                )
                .order_by(AuditLog.created_at)
            )
        )


def test_rows_export_is_generated_in_background_and_downloaded(
    client: TestClient, dispatched: list[tuple[str, list[Any]]]
) -> None:
    owner = register(client)
    ds, version = bi_dataset(client)
    response = _request(client, ds, **PAID_BY_VALUE)
    assert response.status_code == 202, response.text
    export = response.json()
    assert export["status"] == "queued"
    assert export["estimated_rows"] == 4  # a contagem é feita antes de enfileirar
    assert export["version_id"] == version
    assert export["file_name"].startswith("vendas_v1_registros_")
    assert export["file_name"].endswith(".csv")
    assert ("exports.run", [export["id"]]) in dispatched
    # Antes do worker, não há arquivo.
    pending = client.get(f"/api/v1/exports/{export['id']}/download")
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "export_not_ready"

    assert _run(export["id"]) == "succeeded"
    assert _run(export["id"]) == "skipped"  # reentrega da fila vira no-op
    done = client.get(f"/api/v1/exports/{export['id']}").json()
    assert (done["status"], done["row_count"]) == ("succeeded", 4)
    assert done["size_bytes"] > 0
    assert done["expires_at"] is not None

    download = client.get(f"/api/v1/exports/{export['id']}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "text/csv; charset=utf-8"
    assert download.headers["content-disposition"] == f'attachment; filename="{done["file_name"]}"'
    assert download.headers["cache-control"] == "no-store"
    assert download.content.decode("utf-8-sig").splitlines() == [
        "vendedor;valor",
        "Ana Souza;4599,90",
        "Ana Souza;150,00",
        "Bruno Lima;89,90",
        "Bruno Lima;44,95",
    ]
    assert client.get(f"/api/v1/exports/{export['id']}").json()["download_count"] == 1
    history = client.get("/api/v1/exports").json()
    assert [item["id"] for item in history["items"]] == [export["id"]]
    assert _actions(owner["workspace"]["id"]) == ["export.requested", "export.downloaded"]


def test_xlsx_export_neutralizes_formulas(client: TestClient) -> None:
    register(client)
    content = (
        b"produto;valor;observacao\n"
        b'=HYPERLINK("http://exemplo.invalid","clique");10,00;normal\n'
        b"Mouse;-5,00;@SUM(A1)\n"
        b"Teclado;7,50;+5511999999999\n"
    )
    dataset = upload_csv(client, content).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    job = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        json=import_payload(preview),
        headers=csrf(client),
    ).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"
    export = _request(client, dataset["id"], kind="rows", format="xlsx").json()
    assert _run(export["id"]) == "succeeded"
    data = client.get(f"/api/v1/exports/{export['id']}/download").content
    assert "<f>" not in zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
    sheet = load_workbook(io.BytesIO(data)).active
    assert sheet is not None
    values = [[c.value for c in row] for row in sheet.iter_rows(min_row=2)]
    assert values == [
        ['\'=HYPERLINK("http://exemplo.invalid","clique")', 10, "normal"],
        ["Mouse", -5, "'@SUM(A1)"],
        ["Teclado", 7.5, "'+5511999999999"],
    ]


def test_report_export_with_comparison_and_others(client: TestClient) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    export = _request(
        client,
        ds,
        kind="report",
        format="csv",
        report={
            "metrics": [{"aggregation": "sum", "column": "valor"}],
            "dimension": {"column": "equipe"},
            "limit": 2,
            "comparison": {"column": "data_venda", "start": "2025-02-01", "end": "2025-02-28"},
        },
    ).json()
    assert export["file_name"].startswith("vendas_v1_relatorio_")
    assert _run(export["id"]) == "succeeded"
    lines = client.get(f"/api/v1/exports/{export['id']}/download").content.decode("utf-8-sig")
    # Fevereiro contra 04/01–31/01, por equipe; Sul e "sem equipe" vão para "Outros".
    assert lines.splitlines() == [
        "equipe;Soma de valor;Soma de valor (anterior);Variação de Soma de valor (%)",
        "Leste;899,00;;",
        "Norte;150,00;5898,90;-97,46",
        "Outros (2 grupos);44,95;89,90;-50,00",
    ]


def test_limits_are_checked_before_queueing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, dispatched: list[tuple[str, list[Any]]]
) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    monkeypatch.setattr(get_settings(), "export_xlsx_max_rows", 3)
    too_large = _request(client, ds, kind="rows", format="xlsx")
    assert too_large.status_code == 422
    assert too_large.json()["error"]["code"] == "export_too_large"
    assert too_large.json()["error"]["details"] == {"rows": 6, "limit": 3}
    empty = _request(
        client,
        ds,
        kind="rows",
        format="csv",
        rows={"filters": [{"column": "status", "operator": "eq", "value": "inexistente"}]},
    )
    assert empty.json()["error"]["code"] == "export_empty"
    unknown = _request(client, ds, kind="rows", format="csv", rows={"columns": ["senha"]})
    assert unknown.json()["error"]["code"] == "invalid_columns"
    mismatched = _request(client, ds, kind="report", format="csv")
    assert mismatched.status_code == 422
    assert not [d for d in dispatched if d[0] == "exports.run"]

    for _ in range(get_settings().export_active_per_workspace):
        assert _request(client, ds, kind="rows", format="csv").status_code == 202
    busy = _request(client, ds, kind="rows", format="csv")
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "too_many_exports"


def test_viewers_export_only_when_the_admin_allows(client: TestClient) -> None:
    owner = register(client)
    ds, _ = bi_dataset(client)
    viewer = _viewer_of(owner)
    assert _request(viewer, ds, kind="rows", format="csv").status_code == 403
    assert viewer.get("/api/v1/exports").status_code == 403
    allowed = client.patch(
        "/api/v1/workspaces/current",
        json={"settings": {"viewer_exports": True}},
        headers=csrf(client),
    )
    assert allowed.status_code == 200, allowed.text
    assert "data:export" in viewer.get("/api/v1/auth/me").json()["permissions"]
    assert _request(viewer, ds, kind="rows", format="csv").status_code == 202


def test_other_workspace_cannot_see_or_download(client: TestClient) -> None:
    register(client, workspace="Empresa A")
    ds, _ = bi_dataset(client)
    export = _request(client, ds, kind="rows", format="csv").json()
    _run(export["id"])
    intruder = new_client()
    register(intruder, workspace="Empresa B")
    base = f"/api/v1/exports/{export['id']}"
    assert intruder.get(base).status_code == 404
    assert intruder.get(f"{base}/download").status_code == 404
    assert intruder.delete(base, headers=csrf(intruder)).status_code == 404
    assert intruder.get("/api/v1/exports").json()["items"] == []
    # Nem pedir uma exportação apontando para o dataset alheio.
    assert _request(intruder, ds, kind="rows", format="csv").status_code == 404


def test_files_expire_and_are_deleted(client: TestClient, s3: Any) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    export = _request(client, ds, kind="rows", format="csv").json()
    _run(export["id"])
    with session_scope() as db:
        key = db.scalar(
            select(ExportJob.storage_key).where(ExportJob.id == uuid.UUID(export["id"]))
        )
    assert key is not None
    s3.head_object(Bucket=storage.bucket(), Key=key)

    assert expire_exports(utcnow() + timedelta(hours=1)) == 0  # ainda válido (24 h)
    assert expire_exports(utcnow() + timedelta(hours=25)) == 1
    with pytest.raises(ClientError):
        s3.head_object(Bucket=storage.bucket(), Key=key)
    gone = client.get(f"/api/v1/exports/{export['id']}/download")
    assert gone.status_code == 410
    assert gone.json()["error"]["code"] == "export_expired"
    assert client.get(f"/api/v1/exports/{export['id']}").json()["status"] == "expired"


def test_only_the_requester_or_an_admin_deletes(client: TestClient, s3: Any) -> None:
    owner = register(client)
    ds, _ = bi_dataset(client)
    analysts = []
    for name in ("Um", "Dois"):
        analyst = new_client()
        member = register(analyst, workspace=f"Analista {name}")
        add_member(owner["workspace"]["id"], member["user"]["id"], Role.ANALYST)
        analyst.post(
            "/api/v1/workspaces/switch",
            json={"workspace_id": owner["workspace"]["id"]},
            headers=csrf(analyst),
        )
        analysts.append(analyst)
    export = _request(analysts[0], ds, kind="rows", format="csv").json()
    _run(export["id"])
    path = f"/api/v1/exports/{export['id']}"
    assert analysts[1].delete(path, headers=csrf(analysts[1])).status_code == 403
    assert analysts[0].delete(path, headers=csrf(analysts[0])).status_code == 204
    assert client.get(path).status_code == 404
    listed = s3.list_objects_v2(
        Bucket=storage.bucket(), Prefix=f"workspaces/{owner['workspace']['id']}/exports/"
    )
    assert listed.get("KeyCount", 0) == 0


def test_storage_failures_retry_then_fail(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    export = _request(client, ds, kind="rows", format="csv").json()

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise ClientError({"Error": {"Code": "503", "Message": "indisponível"}}, "PutObject")

    monkeypatch.setattr(export_runner.storage, "upload_file", broken)
    with pytest.raises(TransientExportError):
        _run(export["id"])
    queued = client.get(f"/api/v1/exports/{export['id']}").json()
    assert queued["status"] == "queued"
    with pytest.raises(TransientExportError):
        _run(export["id"])
    assert _run(export["id"]) == "failed"  # terceira tentativa: desiste
    failed = client.get(f"/api/v1/exports/{export['id']}").json()
    assert (failed["status"], failed["error_code"]) == ("failed", "armazenamento")


def test_interrupted_exports_are_requeued(
    client: TestClient, dispatched: list[tuple[str, list[Any]]]
) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    export = _request(client, ds, kind="rows", format="csv").json()
    with session_scope() as db:
        db.execute(
            update(ExportJob)
            .where(ExportJob.id == uuid.UUID(export["id"]))
            .values(
                status=ExportStatus.RUNNING,
                attempts=1,
                heartbeat_at=utcnow() - timedelta(hours=1),
            )
        )
    dispatched.clear()
    assert export_runner.recover_exports() == {"requeued": 1, "failed": 0}
    assert dispatched == [("exports.run", [export["id"]])]
    assert _run(export["id"]) == "succeeded"


def test_rows_export_combines_screen_filter_groups(client: TestClient) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    export = _request(
        client,
        ds,
        kind="rows",
        format="csv",
        csv_style="padrao",
        rows={
            "filters": [{"column": "status", "operator": "eq", "value": "pago"}],
            "columns": ["vendedor", "equipe", "valor"],
            # Grupo da tela com o próprio OU: equipe Sul ou sem equipe.
            "extra_filters": [
                {
                    "match": "any",
                    "filters": [
                        {"column": "equipe", "operator": "eq", "value": "Sul"},
                        {"column": "equipe", "operator": "is_null"},
                    ],
                }
            ],
        },
    ).json()
    assert export["estimated_rows"] == 2
    assert _run(export["id"]) == "succeeded"
    body = client.get(f"/api/v1/exports/{export['id']}/download").content.decode("utf-8")
    assert body.splitlines() == [
        "vendedor,equipe,valor",
        "Bruno Lima,Sul,89.90",
        "Bruno Lima,,44.95",
    ]
