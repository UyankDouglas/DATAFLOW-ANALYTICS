"""Transformações pela API: conjuntos de regras, prévia, duplicidades, jobs e linhagem."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import Role
from app.services.job_runner import run_job
from tests.conftest import add_member, csrf, new_client, register, upload_csv
from tests.test_import_flow import import_payload

# Duplicidades propositais: "Ana Souza/Notebook" repete (com espaços diferentes) e uma linha
# idêntica aparece duas vezes; "Eva" fica fora pelo filtro de equipe.
CLEAN_CSV = (
    b"data_venda;vendedor;equipe;produto;quantidade;valor\n"
    b"05/01/2025;Ana Souza;Norte;Notebook;2;4.599,90\n"
    b"06/01/2025; Ana Souza ;Norte;Notebook;1;4.599,90\n"
    b"13/01/2025;Bruno Lima;Sul;Mouse;10;89,90\n"
    b"13/01/2025;Bruno Lima;Sul;Mouse;10;89,90\n"
    b"20/01/2025;Carla Dias;Norte;Monitor;0;1.299,00\n"
    b"21/01/2025;Eva Reis;Oeste;Cadeira;3;899,00\n"
)

RULES: list[dict[str, Any]] = [
    {"operation": "trim", "columns": ["vendedor"]},
    {
        "operation": "filter_rows",
        "match": "all",
        "conditions": [{"column": "equipe", "operator": "ne", "value": "Oeste"}],
    },
    {
        "operation": "derived_column",
        "name": "preco_medio",
        "expression": {
            "kind": "arithmetic",
            "operator": "divide",
            "left": {"column": "valor"},
            "right": {"column": "quantidade"},
            "scale": 2,
        },
    },
    {"operation": "deduplicate", "columns": ["vendedor", "produto"], "keep": "first"},
]


def _processed_dataset(client: TestClient) -> tuple[str, str]:
    dataset = upload_csv(client, CLEAN_CSV).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    job = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        json=import_payload(preview),
        headers=csrf(client),
    ).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"
    detail = client.get(f"/api/v1/datasets/{dataset['id']}").json()
    return dataset["id"], detail["current_version_id"]


def _create_set(
    client: TestClient, ds: str, rules: list[dict] = RULES, name: str = "Limpeza"
) -> Any:
    return client.post(
        f"/api/v1/datasets/{ds}/transformation-sets",
        json={"name": name, "description": "Padroniza e remove duplicidades", "rules": rules},
        headers=csrf(client),
    )


def _apply(client: TestClient, ds: str, version: str, set_id: str, key: str | None = None) -> Any:
    headers = csrf(client) | ({"Idempotency-Key": key} if key else {})
    return client.post(
        f"/api/v1/datasets/{ds}/transform-jobs",
        json={"source_version_id": version, "transformation_set_id": set_id},
        headers=headers,
    )


def test_transformation_creates_new_immutable_version_with_lineage(client: TestClient) -> None:
    register(client)
    ds, v1 = _processed_dataset(client)

    created = _create_set(client, ds)
    assert created.status_code == 201, created.text
    tset = created.json()
    assert tset["revision"] == 1
    assert [r["operation"] for r in tset["rules"]] == [
        "trim",
        "filter_rows",
        "derived_column",
        "deduplicate",
    ]
    assert tset["created_by_name"] == "Pessoa Teste"

    response = _apply(client, ds, v1, tset["id"])
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["kind"] == "transform"
    assert job["source_version_number"] == 1
    assert job["rows_total"] == 6
    assert job["config"]["transformation_set"]["revision"] == 1
    assert run_job(uuid.UUID(job["id"])) == "succeeded"

    done = client.get(f"/api/v1/jobs/{job['id']}").json()
    # 6 recebidos: 1 filtrado (Oeste), 1 rejeitado (divisão por zero), 2 duplicados, 2 válidos.
    assert (done["rows_total"], done["rows_valid"]) == (6, 2)
    assert (done["rows_rejected"], done["rows_filtered"], done["rows_duplicates"]) == (1, 1, 2)
    assert done["rejection_summary"]["by_reason"] == {
        "removido_por_filtro": 1,
        "divisao_por_zero": 1,
        "registro_duplicado": 2,
    }
    assert done["progress_percent"] == 100.0

    versions = client.get(f"/api/v1/datasets/{ds}/versions").json()
    assert [v["version_number"] for v in versions] == [2, 1]
    v2, original = versions
    assert v2["parent_version_id"] == v1
    assert v2["parent_version_number"] == 1
    assert v2["transformation_set_id"] == tset["id"]
    assert (v2["row_count"], v2["rejected_count"]) == (2, 1)
    assert (v2["filtered_count"], v2["duplicate_count"]) == (1, 2)
    assert v2["reconciliation"] == {
        "received": 6,
        "valid": 2,
        "rejected": 1,
        "filtered": 1,
        "duplicates": 2,
        "duplicates_policy": "removidos_dos_validos",
        "consistent": True,
    }
    assert v2["transformations"]["kind"] == "transform"
    assert v2["transformations"]["source_version_number"] == 1
    assert len(v2["transformations"]["steps"]) == 4
    assert [c["name"] for c in v2["column_schema"]][-1] == "preco_medio"
    # A versão de origem continua intacta.
    assert (original["row_count"], original["duplicate_count"]) == (6, None)
    assert original["parent_version_id"] is None

    rows = client.get(f"/api/v1/datasets/{ds}/rows", params={"version_id": v2["id"]}).json()
    by_seller = {r[1]: r for r in rows["rows"]}
    assert set(by_seller) == {"Ana Souza", "Bruno Lima"}
    assert by_seller["Ana Souza"][-1] == "2299.95"  # mantém o primeiro registro (2 unidades)
    assert by_seller["Bruno Lima"][-1] == "8.99"

    excluded = client.get(f"/api/v1/datasets/{ds}/versions/{v2['id']}/rejected").json()
    assert excluded["total"] == 4
    columns = excluded["columns"]
    categories = sorted(r[columns.index("__df_category")] for r in excluded["rows"])
    assert categories == ["duplicado", "duplicado", "filtrado", "rejeitado"]
    duplicate_of = {
        r[columns.index("__df_row")]: r[columns.index("__df_duplicate_of")]
        for r in excluded["rows"]
        if r[columns.index("__df_category")] == "duplicado"
    }
    assert duplicate_of == {2: 1, 4: 3}
    # Valor original preservado como texto (antes do trim).
    ana_dup = next(r for r in excluded["rows"] if r[columns.index("__df_row")] == 2)
    assert ana_dup[columns.index("vendedor")] == " Ana Souza "


def test_reprocessing_chains_versions_and_keeps_rule_snapshot(client: TestClient) -> None:
    register(client)
    ds, v1 = _processed_dataset(client)
    tset = _create_set(client, ds, RULES[:2]).json()
    job = _apply(client, ds, v1, tset["id"]).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"
    v2 = client.get(f"/api/v1/datasets/{ds}").json()["current_version"]

    updated = client.put(
        f"/api/v1/datasets/{ds}/transformation-sets/{tset['id']}",
        json={"name": "Limpeza", "rules": [{"operation": "deduplicate", "columns": []}]},
        headers=csrf(client),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2

    job3 = _apply(client, ds, v2["id"], tset["id"]).json()
    assert job3["config"]["transformation_set"]["revision"] == 2
    assert run_job(uuid.UUID(job3["id"])) == "succeeded"
    versions = {
        v["version_number"]: v for v in client.get(f"/api/v1/datasets/{ds}/versions").json()
    }
    assert versions[3]["parent_version_number"] == 2
    assert versions[3]["reconciliation"]["consistent"] is True
    assert versions[3]["duplicate_count"] == 1  # Bruno Lima repetido em todas as colunas
    # A versão 2 continua registrando as regras da revisão 1.
    assert versions[2]["transformations"]["transformation_set"]["revision"] == 1
    assert [s["operation"] for s in versions[2]["transformations"]["steps"]] == [
        "trim",
        "filter_rows",
    ]


def test_preview_reconciles_sample_and_matches_full_duplicate_analysis(client: TestClient) -> None:
    register(client)
    ds, v1 = _processed_dataset(client)
    response = client.post(
        f"/api/v1/datasets/{ds}/transformations/preview",
        json={"rules": RULES},
        headers=csrf(client),
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    counts = preview["counts"]
    assert counts == {"received": 6, "valid": 2, "rejected": 1, "filtered": 1, "duplicates": 2}
    assert preview["sample_is_complete"] is True
    assert [c["name"] for c in preview["output_columns"]][-1] == "preco_medio"
    assert {r["category"] for r in preview["excluded"]} == {"filtrado", "rejeitado", "duplicado"}

    analysis = client.post(
        f"/api/v1/datasets/{ds}/versions/{v1}/duplicates",
        json={"columns": ["vendedor", "produto"], "keep": "first"},
        headers=csrf(client),
    ).json()
    # Sem o trim, " Ana Souza " é outra chave: só a linha repetida do Bruno é duplicada.
    assert (analysis["total_rows"], analysis["duplicate_rows"], analysis["rows_after"]) == (6, 1, 5)
    assert analysis["top_groups"] == [
        {"key": ["Bruno Lima", "Mouse"], "count": 2, "kept_row": 3, "sample_rows": [3, 4]}
    ]

    # A análise da versão inteira e o job de deduplicação contam o mesmo.
    tset = _create_set(client, ds, [RULES[-1]], name="Só duplicidades").json()
    job = _apply(client, ds, v1, tset["id"]).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"
    done = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert done["rows_duplicates"] == analysis["duplicate_rows"]
    assert done["rows_valid"] == analysis["rows_after"]


def test_duplicate_analysis_groups_nulls_together(client: TestClient) -> None:
    register(client)
    content = b"a;b\n1;\n1;\n2;x\n"
    dataset = upload_csv(client, content).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    job = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        json=import_payload(preview),
        headers=csrf(client),
    ).json()
    run_job(uuid.UUID(job["id"]))
    version = client.get(f"/api/v1/datasets/{dataset['id']}").json()["current_version_id"]
    analysis = client.post(
        f"/api/v1/datasets/{dataset['id']}/versions/{version}/duplicates",
        json={"keep": "last"},
        headers=csrf(client),
    ).json()
    assert analysis["columns"] == ["a", "b"]
    assert analysis["duplicate_rows"] == 1
    assert analysis["top_groups"][0]["key"] == [1, None]
    assert analysis["top_groups"][0]["kept_row"] == 2


@pytest.mark.parametrize(
    ("rules", "fragment"),
    [
        ([{"operation": "trim", "columns": ["inexistente"]}], "inexistente"),
        (
            [
                {"operation": "deduplicate", "columns": []},
                {"operation": "trim", "columns": ["vendedor"]},
            ],
            "última regra",
        ),
    ],
)
def test_invalid_rules_are_refused_with_position(
    client: TestClient, rules: list[dict], fragment: str
) -> None:
    register(client)
    ds, _ = _processed_dataset(client)
    response = _create_set(client, ds, rules)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_rule"
    assert error["details"]["rule_index"] == 0
    assert fragment in error["message"]


@pytest.mark.parametrize(
    "rule",
    [
        {"operation": "eval", "code": "__import__('os').system('id')"},
        {
            "operation": "filter_rows",
            "conditions": [{"column": "valor", "operator": "sql", "value": "1=1"}],
        },
        {"operation": "derived_column", "name": "x", "expression": {"kind": "python", "code": "1"}},
    ],
)
def test_code_like_rules_never_reach_the_engine(client: TestClient, rule: dict) -> None:
    register(client)
    ds, _ = _processed_dataset(client)
    response = _create_set(client, ds, [rule])
    assert response.status_code == 422
    assert client.get(f"/api/v1/datasets/{ds}/transformation-sets").json() == []


def test_set_names_are_unique_per_dataset_and_deletion_keeps_versions(client: TestClient) -> None:
    register(client)
    ds, v1 = _processed_dataset(client)
    tset = _create_set(client, ds, RULES[:1]).json()
    duplicate = _create_set(client, ds, RULES[:1])
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_name"

    job = _apply(client, ds, v1, tset["id"], key="aplicar-1").json()
    again = _apply(client, ds, v1, tset["id"], key="aplicar-1").json()
    assert again["id"] == job["id"]  # mesma chave de idempotência, mesmo job
    busy = _apply(client, ds, v1, tset["id"])
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "job_in_progress"
    assert run_job(uuid.UUID(job["id"])) == "succeeded"

    deleted = client.delete(
        f"/api/v1/datasets/{ds}/transformation-sets/{tset['id']}", headers=csrf(client)
    )
    assert deleted.status_code == 204
    v2 = client.get(f"/api/v1/datasets/{ds}").json()["current_version"]
    assert v2["transformation_set_id"] is None
    assert v2["transformations"]["transformation_set"]["name"] == "Limpeza"


def test_viewer_reads_sets_but_cannot_manage_or_apply(client: TestClient) -> None:
    owner = register(client)
    ds, v1 = _processed_dataset(client)
    tset = _create_set(client, ds).json()

    viewer = new_client()
    member = register(viewer, workspace="Outra")
    add_member(owner["workspace"]["id"], member["user"]["id"], Role.VIEWER)
    switch = viewer.post(
        "/api/v1/workspaces/switch",
        json={"workspace_id": owner["workspace"]["id"]},
        headers=csrf(viewer),
    )
    assert switch.status_code == 200
    assert "transformations:manage" not in viewer.get("/api/v1/auth/me").json()["permissions"]
    assert viewer.get(f"/api/v1/datasets/{ds}/transformation-sets").status_code == 200
    assert _create_set(viewer, ds, name="Outro").status_code == 403
    assert _apply(viewer, ds, v1, tset["id"]).status_code == 403
    preview = viewer.post(
        f"/api/v1/datasets/{ds}/transformations/preview",
        json={"rules": RULES},
        headers=csrf(viewer),
    )
    assert preview.status_code == 403


def test_other_workspace_cannot_reach_transformations(client: TestClient) -> None:
    register(client, workspace="Empresa A")
    ds, v1 = _processed_dataset(client)
    tset = _create_set(client, ds).json()

    intruder = new_client()
    register(intruder, workspace="Empresa B")
    base = f"/api/v1/datasets/{ds}"
    assert intruder.get(f"{base}/transformation-sets").status_code == 404
    assert intruder.get(f"{base}/transformation-sets/{tset['id']}").status_code == 404
    calls = [
        ("put", f"{base}/transformation-sets/{tset['id']}", {"name": "x", "rules": []}),
        ("delete", f"{base}/transformation-sets/{tset['id']}", None),
        ("post", f"{base}/transformation-sets", {"name": "x", "rules": []}),
        ("post", f"{base}/transformations/preview", {"rules": []}),
        ("post", f"{base}/versions/{v1}/duplicates", {"columns": []}),
        (
            "post",
            f"{base}/transform-jobs",
            {"source_version_id": v1, "transformation_set_id": tset["id"]},
        ),
    ]
    for method, path, body in calls:
        kwargs: dict[str, Any] = {"headers": csrf(intruder)}
        if body is not None:
            kwargs["json"] = body
        response = intruder.request(method.upper(), path, **kwargs)
        assert response.status_code == 404, (method, path, response.text)
    # O conjunto segue intacto para o dono.
    assert client.get(f"{base}/transformation-sets/{tset['id']}").json()["revision"] == 1
