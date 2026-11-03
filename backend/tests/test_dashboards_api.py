"""Dashboards persistidos: criação, widgets, versões, filtros, permissões e isolamento."""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import session_scope
from app.models import AuditLog, Role
from app.services.job_runner import run_job
from tests.conftest import add_member, csrf, new_client, register
from tests.test_analytics import bi_dataset
from tests.test_transform_api import _apply, _create_set

KPI = {
    "title": "Faturamento registrado",
    "chart_type": "kpi",
    "size": "small",
    "query": {"metrics": [{"aggregation": "sum", "column": "valor"}]},
}
BY_TEAM = {
    "title": "Registros por equipe",
    "chart_type": "bar",
    "query": {"metrics": [{"aggregation": "count"}], "dimension": {"column": "equipe"}},
}
MONTHLY = {
    "title": "Quantidade por mês",
    "chart_type": "line",
    "size": "large",
    "query": {
        "metrics": [{"aggregation": "sum", "column": "quantidade"}],
        "dimension": {"column": "data_venda", "granularity": "month"},
    },
}


def _create(client: TestClient, ds: str, **body: Any) -> Any:
    payload = {"name": "Vendas", "dataset_id": ds, "widgets": [KPI, BY_TEAM, MONTHLY], **body}
    return client.post("/api/v1/dashboards", json=payload, headers=csrf(client))


def _query(client: TestClient, dashboard: str, widget: str, **body: Any) -> Any:
    return client.post(
        f"/api/v1/dashboards/{dashboard}/query",
        json={"widget_id": widget, **body},
        headers=csrf(client),
    )


def _viewer_of(owner: dict[str, Any]) -> TestClient:
    viewer = new_client()
    member = register(viewer, workspace="Outra")
    add_member(owner["workspace"]["id"], member["user"]["id"], Role.VIEWER)
    viewer.post(
        "/api/v1/workspaces/switch",
        json={"workspace_id": owner["workspace"]["id"]},
        headers=csrf(viewer),
    )
    return viewer


def test_create_reopen_and_query_widgets(client: TestClient) -> None:
    register(client)
    ds, version = bi_dataset(client)
    created = _create(client, ds, description="Acompanhamento mensal")
    assert created.status_code == 201, created.text
    dashboard = created.json()
    assert [w["title"] for w in dashboard["widgets"]] == [
        "Faturamento registrado",
        "Registros por equipe",
        "Quantidade por mês",
    ]
    assert [w["position"] for w in dashboard["widgets"]] == [0, 1, 2]
    assert dashboard["version_id"] is None  # acompanha a versão atual
    assert dashboard["resolved_version_id"] == version
    assert dashboard["created_by_name"] == "Pessoa Teste"

    # Reabrir devolve a mesma configuração, com os padrões da consulta preenchidos.
    reopened = client.get(f"/api/v1/dashboards/{dashboard['id']}").json()
    assert reopened["widgets"] == dashboard["widgets"]
    assert reopened["widgets"][1]["query"]["limit"] == 10

    listed = client.get("/api/v1/dashboards").json()
    assert [(d["name"], d["widget_count"], d["chart_types"]) for d in listed] == [
        ("Vendas", 3, ["kpi", "bar", "line"])
    ]
    assert listed[0]["dataset_name"] == "vendas"

    kpi_id, bar_id, line_id = (w["id"] for w in dashboard["widgets"])
    kpi = _query(client, dashboard["id"], kpi_id)
    assert kpi.status_code == 200, kpi.text
    assert kpi.json()["result"]["rows"][0]["values"] == ["7082.75"]
    bars = _query(client, dashboard["id"], bar_id).json()["result"]
    assert [(r["key"], r["values"][0]) for r in bars["rows"]][:1] == [("Norte", 3)]
    line = _query(client, dashboard["id"], line_id).json()["result"]
    assert [r["values"][0] for r in line["rows"]] == [13, 9]


def test_saved_and_screen_filters_are_combined(client: TestClient) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    dashboard = _create(
        client,
        ds,
        filters={"filters": [{"column": "status", "operator": "eq", "value": "pago"}]},
    ).json()
    kpi_id = dashboard["widgets"][0]["id"]
    # Filtro salvo: só vendas pagas (4.599,90 + 89,90 + 150,00 + 44,95).
    assert _query(client, dashboard["id"], kpi_id).json()["result"]["rows"][0]["values"] == [
        "4884.75"
    ]
    # Filtro da tela: período de fevereiro, somado ao salvo.
    february = [
        {"column": "data_venda", "operator": "gte", "value": "2025-02-01"},
        {"column": "data_venda", "operator": "lte", "value": "2025-02-28"},
    ]
    result = _query(client, dashboard["id"], kpi_id, extra_filters=[{"filters": february}]).json()[
        "result"
    ]
    assert result["rows"][0]["values"] == ["194.95"]
    assert result["matched_rows"] == 2
    invalid = _query(
        client,
        dashboard["id"],
        kpi_id,
        extra_filters=[
            {"filters": [{"column": "status", "operator": "is_null"}]},
            {"filters": [{"column": "valor", "operator": "contains", "value": "1"}]},
        ],
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_filter"
    # Dois grupos da tela, cada um com o próprio E/OU: pagos (salvo) e (Sul ou sem equipe).
    either = _query(
        client,
        dashboard["id"],
        kpi_id,
        extra_filters=[
            {
                "match": "any",
                "filters": [
                    {"column": "equipe", "operator": "eq", "value": "Sul"},
                    {"column": "equipe", "operator": "is_null"},
                ],
            }
        ],
    ).json()["result"]
    assert either["rows"][0]["values"] == ["134.85"]  # 89,90 + 44,95


def test_patch_reorders_keeps_ids_and_pins_versions(client: TestClient) -> None:
    register(client)
    ds, v1 = bi_dataset(client)
    dashboard = _create(client, ds).json()
    kpi, bar, line = dashboard["widgets"]
    path = f"/api/v1/dashboards/{dashboard['id']}"

    reordered = client.patch(
        path,
        json={
            "name": "Vendas 2025",
            "widgets": [
                {**MONTHLY, "id": line["id"]},
                {**KPI, "id": kpi["id"], "size": "medium"},
                {**BY_TEAM, "title": "Por equipe", "chart_type": "table"},
            ],
        },
        headers=csrf(client),
    )
    assert reordered.status_code == 200, reordered.text
    widgets = reordered.json()["widgets"]
    assert [w["id"] for w in widgets[:2]] == [line["id"], kpi["id"]]
    assert widgets[2]["id"] not in {kpi["id"], bar["id"], line["id"]}  # sem id = novo widget
    assert [w["size"] for w in widgets] == ["large", "medium", "medium"]
    assert reordered.json()["name"] == "Vendas 2025"
    # O widget removido deixa de existir.
    assert _query(client, dashboard["id"], bar["id"]).status_code == 404

    # Uma nova versão (transformação) passa a valer para quem acompanha a atual…
    tset = _create_set(
        client,
        ds,
        rules=[
            {
                "operation": "filter_rows",
                "conditions": [{"column": "status", "operator": "eq", "value": "pago"}],
            }
        ],
    ).json()
    job = _apply(client, ds, v1, tset["id"]).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"
    current = _query(client, dashboard["id"], kpi["id"]).json()["result"]
    assert (current["version_number"], current["rows"][0]["values"]) == (2, ["4884.75"])

    # …e fixar a versão 1 congela os números, mesmo com a versão 2 publicada.
    pinned = client.patch(path, json={"version_id": v1}, headers=csrf(client)).json()
    assert (pinned["version_number"], pinned["resolved_version_number"]) == (1, 1)
    frozen = _query(client, dashboard["id"], kpi["id"]).json()["result"]
    assert (frozen["version_number"], frozen["rows"][0]["values"]) == (1, ["7082.75"])
    unpinned = client.patch(path, json={"version_id": None}, headers=csrf(client)).json()
    assert (unpinned["version_id"], unpinned["resolved_version_number"]) == (None, 2)


def test_widgets_are_validated_against_the_version(client: TestClient) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    cases = [
        (
            {
                **BY_TEAM,
                "chart_type": "pie",
                "query": {
                    **BY_TEAM["query"],
                    "metrics": [{"aggregation": "avg", "column": "valor"}],
                },
            },
            "partes de um todo",
        ),
        ({**KPI, "query": {**KPI["query"], "dimension": {"column": "equipe"}}}, "único número"),
        ({**BY_TEAM, "query": {"metrics": [{"aggregation": "count"}]}}, "dimensão"),
        (
            {
                **BY_TEAM,
                "query": {
                    **BY_TEAM["query"],
                    "metrics": [{"aggregation": "sum", "column": "inexistente"}],
                },
            },
            "coluna desconhecida",
        ),
        (
            {
                **MONTHLY,
                "query": {
                    **MONTHLY["query"],
                    "comparison": {
                        "column": "data_venda",
                        "start": "2025-02-01",
                        "end": "2025-02-28",
                    },
                },
            },
            "remova a comparação",
        ),
    ]
    for widget, message in cases:
        response = _create(client, ds, name=f"Inválido {message}", widgets=[KPI, widget])
        assert response.status_code == 422, (message, response.text)
        error = response.json()["error"]
        assert error["code"] == "invalid_widget"
        assert error["details"]["widget_index"] == 1
        assert message in error["message"], error["message"]

    assert _create(client, ds).status_code == 201
    duplicate = _create(client, ds)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_name"
    bad_filter = _create(
        client,
        ds,
        name="Filtro ruim",
        filters={"filters": [{"column": "valor", "operator": "eq", "value": "abc"}]},
    )
    assert bad_filter.status_code == 422
    assert bad_filter.json()["error"]["code"] == "invalid_filter"


def test_widget_incompatible_after_schema_change(client: TestClient) -> None:
    register(client)
    ds, v1 = bi_dataset(client)
    dashboard = _create(client, ds).json()
    bar_id = dashboard["widgets"][1]["id"]
    tset = _create_set(
        client, ds, rules=[{"operation": "rename_columns", "mapping": {"equipe": "time"}}]
    ).json()
    job = _apply(client, ds, v1, tset["id"]).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"

    response = _query(client, dashboard["id"], bar_id)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "widget_incompatible"
    assert "versão 2" in error["message"]
    # Os outros widgets continuam funcionando.
    assert _query(client, dashboard["id"], dashboard["widgets"][0]["id"]).status_code == 200
    # Salvar exige corrigir o widget (ou fixar a versão 1, compatível).
    rename = client.patch(
        f"/api/v1/dashboards/{dashboard['id']}", json={"name": "Novo"}, headers=csrf(client)
    )
    assert rename.status_code == 422
    assert rename.json()["error"]["code"] == "invalid_widget"
    pin = client.patch(
        f"/api/v1/dashboards/{dashboard['id']}", json={"version_id": v1}, headers=csrf(client)
    )
    assert pin.status_code == 200


def test_permissions_viewer_reads_and_filters_only(client: TestClient) -> None:
    owner = register(client)
    ds, _ = bi_dataset(client)
    dashboard = _create(client, ds).json()
    viewer = _viewer_of(owner)
    assert "dashboards:manage" not in viewer.get("/api/v1/auth/me").json()["permissions"]
    path = f"/api/v1/dashboards/{dashboard['id']}"
    assert viewer.get("/api/v1/dashboards").status_code == 200
    assert viewer.get(path).status_code == 200
    kpi_id = dashboard["widgets"][0]["id"]
    assert _query(viewer, dashboard["id"], kpi_id).status_code == 200
    assert (
        viewer.post(
            f"/api/v1/datasets/{ds}/analytics",
            json={"metrics": [{"aggregation": "count"}]},
            headers=csrf(viewer),
        ).status_code
        == 200
    )
    assert _create(viewer, ds, name="Do visualizador").status_code == 403
    assert viewer.patch(path, json={"name": "x"}, headers=csrf(viewer)).status_code == 403
    assert viewer.delete(path, headers=csrf(viewer)).status_code == 403

    analyst = new_client()
    member = register(analyst, workspace="Do analista")
    add_member(owner["workspace"]["id"], member["user"]["id"], Role.ANALYST)
    analyst.post(
        "/api/v1/workspaces/switch",
        json={"workspace_id": owner["workspace"]["id"]},
        headers=csrf(analyst),
    )
    assert _create(analyst, ds, name="Do analista").status_code == 201


def test_other_workspace_cannot_reach_dashboards(client: TestClient) -> None:
    register(client, workspace="Empresa A")
    ds, version = bi_dataset(client)
    dashboard = _create(client, ds).json()
    intruder = new_client()
    register(intruder, workspace="Empresa B")
    path = f"/api/v1/dashboards/{dashboard['id']}"
    assert intruder.get("/api/v1/dashboards").json() == []
    assert intruder.get(path).status_code == 404
    assert intruder.patch(path, json={"name": "x"}, headers=csrf(intruder)).status_code == 404
    assert intruder.delete(path, headers=csrf(intruder)).status_code == 404
    assert _query(intruder, dashboard["id"], dashboard["widgets"][0]["id"]).status_code == 404
    # Nem criar um dashboard apontando para o dataset (ou a versão) de outro workspace.
    assert _create(intruder, ds, name="Alheio").status_code == 404
    own, _ = bi_dataset(intruder)
    foreign_version = _create(intruder, own, name="Versão alheia", version_id=version)
    assert foreign_version.status_code == 404


def test_delete_and_audit(client: TestClient) -> None:
    owner = register(client)
    ds, _ = bi_dataset(client)
    dashboard = _create(client, ds).json()
    path = f"/api/v1/dashboards/{dashboard['id']}"
    assert (
        client.patch(path, json={"description": "Atualizado"}, headers=csrf(client)).status_code
        == 200
    )
    assert client.delete(path, headers=csrf(client)).status_code == 204
    assert client.get(path).status_code == 404
    with session_scope() as db:
        actions = db.scalars(
            select(AuditLog.action)
            .where(
                AuditLog.workspace_id == uuid.UUID(owner["workspace"]["id"]),
                AuditLog.entity_type == "dashboard",
            )
            .order_by(AuditLog.created_at)
        ).all()
    assert actions == ["dashboard.created", "dashboard.updated", "dashboard.deleted"]
