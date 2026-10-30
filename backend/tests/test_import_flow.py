"""Fluxo completo: upload → preview → importação → worker → versão → consulta paginada."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.db import session_scope
from app.models import DatasetVersion, JobStatus, ProcessingJob
from app.models.base import utcnow
from app.services import job_runner
from app.services.job_runner import TransientJobError, recover_jobs, run_import_job
from tests.conftest import SALES_CSV, csrf, register, upload_csv


def import_payload(
    preview: dict[str, Any], types: dict[str, str] | None = None, **overrides: Any
) -> dict[str, Any]:
    columns = []
    for col in preview["columns"]:
        columns.append(
            {
                "position": col["position"],
                "source_name": col["source_name"],
                "name": col["source_name"],
                "data_type": (types or {}).get(col["source_name"], col["inferred_type"]),
                "format": col["format"],
                "scale": col["scale"],
            }
        )
    return {"parse_options": preview["parse_options"], "columns": columns, **overrides}


def _start(client: TestClient, content: bytes = SALES_CSV, **overrides: Any) -> tuple[dict, dict]:
    dataset = upload_csv(client, content).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    # "quantidade" contém "x" na amostra (inferida como texto); forçar inteiro gera rejeição.
    payload = import_payload(preview, types={"quantidade": "integer"}, **overrides)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports", json=payload, headers=csrf(client)
    )
    assert response.status_code == 202, response.text
    return dataset, response.json()


def test_full_import_publishes_version_and_serves_rows(
    client: TestClient, dispatched: list
) -> None:
    register(client)
    dataset, job = _start(client)
    assert job["status"] == "queued"
    assert ("imports.run", [job["id"]]) in dispatched

    assert run_import_job(uuid.UUID(job["id"])) == "succeeded"

    done = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert done["status"] == "succeeded"
    assert done["progress_percent"] == 100.0
    assert (done["rows_total"], done["rows_valid"], done["rows_rejected"]) == (6, 3, 3)
    assert done["rejection_summary"]["by_reason"] == {
        "tipo_invalido": 1,
        "linha_vazia": 1,
        "campos_a_menos": 1,
    }
    assert done["rejection_summary"]["by_column"] == {"quantidade": 1}
    assert {"row", "line", "reason", "column", "detail"} == set(
        done["rejection_summary"]["samples"][0]
    )
    assert done["result_version_number"] == 1
    assert "processing" in done["metrics"]["timings_ms"]

    detail = client.get(f"/api/v1/datasets/{dataset['id']}").json()
    assert detail["status"] == "ready"
    assert detail["current_version"]["reconciliation"]["consistent"] is True
    assert next(c["name"] for c in detail["columns"]) == "data_venda"

    rows = client.get(
        f"/api/v1/datasets/{dataset['id']}/rows?page=1&page_size=2&sort=valor&direction=desc"
    ).json()
    assert rows["total"] == 3
    assert rows["page_size"] == 2
    assert [c["name"] for c in rows["columns"]][:2] == ["data_venda", "vendedor"]
    valor_index = [c["name"] for c in rows["columns"]].index("valor")
    assert [r[valor_index] for r in rows["rows"]] == [
        "4599.90",
        "1299.00",
    ]  # decimal trafega como texto
    page2 = client.get(
        f"/api/v1/datasets/{dataset['id']}/rows?page=2&page_size=2&sort=valor&direction=desc"
    ).json()
    assert len(page2["rows"]) == 1

    rejected = client.get(
        f"/api/v1/datasets/{dataset['id']}/versions/{detail['current_version_id']}/rejected"
    ).json()
    assert rejected["total"] == 3
    reasons = {r[2] for r in rejected["rows"]}
    assert reasons == {"tipo_invalido", "linha_vazia", "campos_a_menos"}


def test_rows_query_rejects_unknown_columns(client: TestClient) -> None:
    register(client)
    dataset, job = _start(client)
    run_import_job(uuid.UUID(job["id"]))
    bad_sort = client.get(f"/api/v1/datasets/{dataset['id']}/rows?sort=valor%22%3B%20DROP")
    assert bad_sort.status_code == 422
    bad_column = client.get(f"/api/v1/datasets/{dataset['id']}/rows?columns=nao_existe")
    assert bad_column.status_code == 422
    too_big = client.get(f"/api/v1/datasets/{dataset['id']}/rows?page_size=5000")
    assert too_big.status_code == 422


def test_import_validation_errors(client: TestClient) -> None:
    register(client)
    dataset = upload_csv(client, SALES_CSV).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()

    payload = import_payload(preview)
    payload["columns"][1]["name"] = "Data_Venda"  # duplicado sem diferenciar maiúsculas
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports", json=payload, headers=csrf(client)
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "duplicate_column_names"

    payload = import_payload(preview)
    payload["columns"] = payload["columns"][:-1]
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports", json=payload, headers=csrf(client)
    )
    assert response.json()["error"]["code"] == "column_count_mismatch"

    payload = import_payload(preview)
    payload["columns"][0]["source_name"] = "outra"
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports", json=payload, headers=csrf(client)
    )
    assert response.json()["error"]["code"] == "header_mismatch"


def test_ambiguous_dates_require_confirmation(client: TestClient) -> None:
    register(client)
    content = b"data,valor\n01/02/2024,10\n03/04/2024,20\n"
    dataset = upload_csv(client, content).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        json=import_payload(preview),
        headers=csrf(client),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ambiguous_formats_not_confirmed"
    confirmed = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        json=import_payload(preview, confirm_ambiguous_formats=True),
        headers=csrf(client),
    )
    assert confirmed.status_code == 202


def test_idempotency_key_and_single_active_job(client: TestClient) -> None:
    register(client)
    dataset = upload_csv(client, SALES_CSV).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    url = f"/api/v1/datasets/{dataset['id']}/imports"
    headers = {**csrf(client), "Idempotency-Key": "clique-duplo-1"}
    first = client.post(url, json=import_payload(preview), headers=headers).json()
    second = client.post(url, json=import_payload(preview), headers=headers).json()
    assert first["id"] == second["id"]

    other = client.post(url, json=import_payload(preview), headers=csrf(client))
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "job_in_progress"


def test_duplicate_delivery_is_noop_and_reprocessing_creates_new_version(
    client: TestClient,
) -> None:
    register(client)
    dataset, job = _start(client)
    job_id = uuid.UUID(job["id"])
    assert run_import_job(job_id) == "succeeded"
    assert run_import_job(job_id) == "skipped"  # reentrega da mesma mensagem

    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    payload = import_payload(preview)
    for column in payload["columns"]:
        if column["source_name"] == "valor":
            column["data_type"], column["scale"] = "text", None
    second = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports", json=payload, headers=csrf(client)
    ).json()
    assert run_import_job(uuid.UUID(second["id"])) == "succeeded"

    versions = client.get(f"/api/v1/datasets/{dataset['id']}/versions").json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[0]["column_schema"][5]["data_type"] == "text"
    assert versions[1]["column_schema"][5]["data_type"] == "decimal"  # versão anterior imutável
    v1 = client.get(f"/api/v1/datasets/{dataset['id']}/rows?version_id={versions[1]['id']}").json()
    assert v1["version_number"] == 1


def test_cancel_queued_job(client: TestClient) -> None:
    register(client)
    dataset, job = _start(client)
    response = client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=csrf(client))
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert run_import_job(uuid.UUID(job["id"])) == "skipped"
    assert client.get(f"/api/v1/datasets/{dataset['id']}").json()["status"] == "draft"
    again = client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=csrf(client))
    assert again.status_code == 409


def test_cooperative_cancel_stops_running_job_without_publishing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    _dataset, job = _start(client)
    job_id = uuid.UUID(job["id"])
    original = job_runner._report_progress

    def cancel_during_processing(jid: uuid.UUID, progress: Any) -> None:
        with session_scope() as db:
            db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == jid)
                .values(cancel_requested_at=utcnow())
            )
        original(jid, progress)

    monkeypatch.setattr(job_runner, "_report_progress", cancel_during_processing)
    assert run_import_job(job_id) == "cancelled"
    final = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert final["status"] == "cancelled"
    assert final["result_version_id"] is None
    with session_scope() as db:
        assert db.scalar(select(DatasetVersion.id).where(DatasetVersion.job_id == job_id)) is None


def test_transient_failure_requeues_then_fails_after_max_attempts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    dataset, job = _start(client)
    job_id = uuid.UUID(job["id"])

    def broken_download(*_: Any) -> None:
        raise EndpointConnectionError(endpoint_url="http://minio:9000")

    monkeypatch.setattr(job_runner.storage, "download_file", broken_download)
    for attempt in (1, 2):
        with pytest.raises(TransientJobError):
            run_import_job(job_id)
        state = client.get(f"/api/v1/jobs/{job['id']}").json()
        assert state["status"] == "queued"
        assert state["attempts"] == attempt
        assert len(state["warnings"]) == attempt
    assert run_import_job(job_id) == "failed"
    final = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert final["status"] == "failed"
    assert final["error_code"] == "indisponibilidade"
    assert client.get(f"/api/v1/datasets/{dataset['id']}").json()["status"] == "failed"


def test_permanent_failure_is_reported_with_clear_message(client: TestClient) -> None:
    register(client)
    content = "nome;cidade\nJoão;São Paulo\n".encode("cp1252") + b"x" * 10
    dataset = upload_csv(client, content, "latin.csv").json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    payload = import_payload(preview)
    payload["parse_options"]["encoding"] = "iso-8859-1"
    job = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports", json=payload, headers=csrf(client)
    ).json()
    assert run_import_job(uuid.UUID(job["id"])) == "succeeded"


def test_recover_jobs_requeues_stale_execution(client: TestClient, dispatched: list) -> None:
    register(client)
    _, job = _start(client)
    job_id = uuid.UUID(job["id"])
    with session_scope() as db:
        db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(
                status=JobStatus.PROCESSING, attempts=1, heartbeat_at=utcnow() - timedelta(hours=1)
            )
        )
    dispatched.clear()
    stats = recover_jobs()
    assert stats["requeued"] == 1
    assert ("imports.run", [str(job_id)]) in dispatched
    assert run_import_job(job_id) == "succeeded"
    final = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert final["attempts"] == 2
    assert any("reenfileirado" in w["message"] for w in final["warnings"])


def test_overview_reports_real_counts(client: TestClient) -> None:
    register(client)
    empty = client.get("/api/v1/overview").json()
    assert empty["datasets_total"] == 0
    assert empty["recent_jobs"] == []
    _, job = _start(client)
    run_import_job(uuid.UUID(job["id"]))
    overview = client.get("/api/v1/overview").json()
    assert overview["datasets_total"] == 1
    assert overview["datasets_ready"] == 1
    assert overview["rows_published"] == 3
    assert overview["jobs_succeeded_7d"] == 1
    assert overview["rows_rejected_7d"] == 3
    assert len(overview["jobs_by_day"]) == 14
    assert overview["recent_jobs"][0]["dataset_name"] == "vendas"
