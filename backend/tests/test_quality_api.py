"""Qualidade e Data Explorer pela API: relatório por versão, inconsistências e consultas."""

import uuid
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.analytics import query as query_module
from app.core.db import session_scope
from app.core.errors import ValidationFailed
from app.models import QualityReport, Role
from app.services import quality_service
from app.services.job_runner import run_job
from tests.conftest import SALES_CSV, add_member, csrf, new_client, register, upload_csv
from tests.test_import_flow import import_payload
from tests.test_transform_api import _apply, _create_set, _processed_dataset


def _imported_sales(client: TestClient) -> tuple[str, str]:
    dataset = upload_csv(client, SALES_CSV).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    payload = import_payload(preview, types={"quantidade": "integer"})
    job = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports", json=payload, headers=csrf(client)
    ).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"
    version = client.get(f"/api/v1/datasets/{dataset['id']}").json()["current_version_id"]
    return dataset["id"], version


def test_worker_publishes_quality_report_with_the_version(client: TestClient) -> None:
    register(client)
    ds, version = _imported_sales(client)
    response = client.get(f"/api/v1/datasets/{ds}/versions/{version}/quality")
    assert response.status_code == 200, response.text
    report = response.json()
    indicators = report["metrics"]["indicators"]
    # SALES_CSV: 6 recebidos, 3 válidos, 3 rejeitados (tipo, linha vazia, campos a menos).
    assert (indicators["received"], indicators["valid"], indicators["rejected"]) == (6, 3, 3)
    assert indicators["rules_violated"] == 3
    assert indicators["columns_with_issues"] == 1
    assert report["metrics"]["components"]["validity"] == pytest.approx(0.5)
    assert report["formula_version"] == "1.0"
    assert report["computed_by_name"] is None  # calculado pelo worker
    issues = {(i["reason"], i["column"]): i for i in report["issues"]}
    assert (
        issues[("tipo_invalido", "quantidade")]["rule_label"] == "Leitura e mapeamento do arquivo"
    )
    versions = client.get(f"/api/v1/datasets/{ds}/versions").json()
    assert versions[0]["quality_score"] == report["score"]


def test_report_on_demand_comparison_and_permissions(client: TestClient) -> None:
    owner = register(client)
    ds, v1 = _processed_dataset(client)
    tset = _create_set(client, ds).json()
    job = _apply(client, ds, v1, tset["id"]).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"

    with session_scope() as db:
        db.execute(delete(QualityReport).where(QualityReport.version_id == uuid.UUID(v1)))
    missing = client.get(f"/api/v1/datasets/{ds}/versions/{v1}/quality")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "quality_not_computed"

    comparison = client.get(f"/api/v1/datasets/{ds}/quality").json()
    assert [(c["version_number"], c["computed"]) for c in comparison] == [(1, False), (2, True)]
    v2 = comparison[1]
    assert v2["parent_version_number"] == 1
    assert v2["kind"] == "transform"
    assert v2["indicators"]["duplicates_removed"] == 2
    assert v2["indicators"]["filtered"] == 1

    viewer = new_client()
    member = register(viewer, workspace="Outra")
    add_member(owner["workspace"]["id"], member["user"]["id"], Role.VIEWER)
    viewer.post(
        "/api/v1/workspaces/switch",
        json={"workspace_id": owner["workspace"]["id"]},
        headers=csrf(viewer),
    )
    denied = viewer.post(f"/api/v1/datasets/{ds}/versions/{v1}/quality", headers=csrf(viewer))
    assert denied.status_code == 403
    assert viewer.get(f"/api/v1/datasets/{ds}/quality").status_code == 200
    # A análise de duplicidades é só leitura e alimenta a tela Qualidade.
    analysis = viewer.post(
        f"/api/v1/datasets/{ds}/versions/{v1}/duplicates",
        json={"columns": ["vendedor"]},
        headers=csrf(viewer),
    )
    assert analysis.status_code == 200, analysis.text

    computed = client.post(f"/api/v1/datasets/{ds}/versions/{v1}/quality", headers=csrf(client))
    assert computed.status_code == 200, computed.text
    assert computed.json()["computed_by_name"] == "Pessoa Teste"
    again = client.post(f"/api/v1/datasets/{ds}/versions/{v1}/quality", headers=csrf(client))
    assert again.json()["id"] == computed.json()["id"]  # recalcular substitui, não duplica
    assert all(c["computed"] for c in client.get(f"/api/v1/datasets/{ds}/quality").json())


def test_inconsistencies_explain_rule_and_treatment(client: TestClient) -> None:
    register(client)
    ds, v1 = _processed_dataset(client)
    tset = _create_set(client, ds).json()
    job = _apply(client, ds, v1, tset["id"]).json()
    run_job(uuid.UUID(job["id"]))
    v2 = client.get(f"/api/v1/datasets/{ds}").json()["current_version_id"]
    base = f"/api/v1/datasets/{ds}/versions/{v2}/quality/inconsistencies"

    everything = client.get(base).json()
    assert everything["total"] == 4
    duplicates = client.get(base, params={"category": "duplicado"}).json()
    assert duplicates["total"] == 2
    first = duplicates["items"][0]
    assert first["rule_label"] == "Regra 4: Remover duplicidades"
    assert first["treatment"] == "Removido como duplicado; mantido o registro 1"
    assert first["record"]["vendedor"] == " Ana Souza "  # valor de entrada, antes do trim

    division = client.get(base, params={"reason": "divisao_por_zero"}).json()["items"]
    assert len(division) == 1
    assert division[0]["column"] == "preco_medio"
    assert division[0]["rule_label"] == "Regra 3: Criar coluna derivada"
    assert division[0]["category"] == "rejeitado"

    paged = client.get(base, params={"page": 2, "page_size": 3}).json()
    assert (paged["total"], len(paged["items"])) == (4, 1)
    assert client.get(base, params={"category": "outro"}).status_code == 422


def test_value_frequency_reads_the_version(client: TestClient) -> None:
    register(client)
    ds, v1 = _processed_dataset(client)
    response = client.get(
        f"/api/v1/datasets/{ds}/versions/{v1}/quality/values", params={"column": "equipe"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["nulls"], body["distinct"]) == (6, 0, 3)  # Norte, Sul, Oeste
    assert body["values"][0] == {"value": "Norte", "count": 3}
    assert body["others"] == 0
    unknown = client.get(
        f"/api/v1/datasets/{ds}/versions/{v1}/quality/values", params={"column": 'x"; DROP'}
    )
    assert unknown.status_code == 422


def _query(client: TestClient, ds: str, **body: Any) -> Any:
    return client.post(f"/api/v1/datasets/{ds}/rows/query", json=body, headers=csrf(client))


def test_explorer_filters_search_columns_and_counts(client: TestClient) -> None:
    register(client)
    ds, _ = _processed_dataset(client)

    rows = _query(
        client,
        ds,
        filters=[
            {"column": "equipe", "operator": "eq", "value": "norte", "case_insensitive": True}
        ],
        columns=["valor", "vendedor"],
        sort="valor",
        direction="desc",
    ).json()
    assert (rows["total"], rows["total_unfiltered"]) == (3, 6)
    assert [c["name"] for c in rows["columns"]] == ["valor", "vendedor"]
    assert [r[0] for r in rows["rows"]] == ["4599.90", "4599.90", "1299.00"]

    between = _query(
        client,
        ds,
        filters=[
            {"column": "valor", "operator": "between", "value": "80", "value_to": "1300"},
            {"column": "data_venda", "operator": "gte", "value": "2025-01-13"},
        ],
    ).json()
    assert between["total"] == 4  # dois Mouse (89,90), Monitor (1.299,00) e Cadeira (899,00)

    listed = _query(
        client,
        ds,
        match="any",
        filters=[
            {"column": "produto", "operator": "in", "values": ["Cadeira", "Monitor"]},
            {"column": "quantidade", "operator": "eq", "value": "10"},
        ],
    ).json()
    assert listed["total"] == 4

    searched = _query(client, ds, search="lima").json()
    assert searched["total"] == 2
    # % e _ são texto literal na busca, não curingas.
    assert _query(client, ds, search="%").json()["total"] == 0
    assert _query(client, ds, search="Ana_").json()["total"] == 0

    unfiltered = _query(client, ds).json()
    assert unfiltered["total"] == unfiltered["total_unfiltered"] == 6


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            {"filters": [{"column": 'x"; DROP TABLE t; --', "operator": "eq", "value": "1"}]},
            "invalid_filter",
        ),
        (
            {"filters": [{"column": "valor", "operator": "contains", "value": "1"}]},
            "invalid_filter",
        ),
        (
            {"filters": [{"column": "valor", "operator": "eq", "value": "1; DROP"}]},
            "invalid_filter",
        ),
        (
            {"filters": [{"column": "data_venda", "operator": "eq", "value": "31/02/2025"}]},
            "invalid_filter",
        ),
        ({"columns": ["__df_row"]}, "validation_error"),
        ({"sort": "valor desc; --"}, "validation_error"),
        ({"filters": [{"column": "valor", "operator": "sql", "value": "1=1"}]}, "validation_error"),
    ],
)
def test_explorer_rejects_unsafe_or_invalid_queries(
    client: TestClient, body: dict[str, Any], code: str
) -> None:
    register(client)
    ds, _ = _processed_dataset(client)
    response = _query(client, ds, **body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code


def test_query_timeout_interrupts_expensive_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_module, "QUERY_TIMEOUT_SECONDS", 0.2)
    con = duckdb.connect()
    try:
        with pytest.raises(ValidationFailed) as error:
            query_module.run_limited(con, "SELECT count(*) FROM range(10000000000) t(x)", {})
    finally:
        con.close()
    assert error.value.code == "query_timeout"


def test_failed_quality_report_keeps_the_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise duckdb.IOException("disco cheio")

    monkeypatch.setattr(quality_service, "build_report", boom)
    ds, version = _imported_sales(client)
    job = client.get(f"/api/v1/jobs?dataset_id={ds}").json()["items"][0]
    assert job["status"] == "succeeded"
    assert any("Relatório de qualidade não calculado" in w["message"] for w in job["warnings"])
    response = client.get(f"/api/v1/datasets/{ds}/versions/{version}/quality")
    assert response.json()["error"]["code"] == "quality_not_computed"


def test_other_workspace_cannot_reach_quality_or_queries(client: TestClient) -> None:
    register(client, workspace="Empresa A")
    ds, version = _processed_dataset(client)
    intruder = new_client()
    register(intruder, workspace="Empresa B")
    base = f"/api/v1/datasets/{ds}"
    for path in (
        f"{base}/quality",
        f"{base}/versions/{version}/quality",
        f"{base}/versions/{version}/quality/inconsistencies",
        f"{base}/versions/{version}/quality/values?column=equipe",
    ):
        assert intruder.get(path).status_code == 404, path
    assert (
        intruder.post(f"{base}/versions/{version}/quality", headers=csrf(intruder)).status_code
        == 404
    )
    assert _query(intruder, ds).status_code == 404
