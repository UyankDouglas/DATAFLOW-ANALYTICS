"""Consultas analíticas: KPIs, agrupamentos, séries, comparação entre períodos e validação."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.analytics import aggregate
from app.analytics.aggregate import AggregateSpec, plan_aggregate
from app.core.errors import ValidationFailed
from app.processing.types import ColumnSpec
from app.services.job_runner import run_job
from tests.conftest import csrf, new_client, register, upload_csv
from tests.test_import_flow import import_payload

# Seis vendas em dois meses; a última não tem equipe (nulo). Totais conferidos à mão:
# soma de valor 7.082,75; janeiro 5.988,80 e fevereiro 1.093,95; quantidade 13 e 9.
BI_CSV = (
    b"data_venda;vendedor;equipe;produto;quantidade;valor;status\n"
    b"05/01/2025;Ana Souza;Norte;Notebook;2;4.599,90;pago\n"
    b"13/01/2025;Bruno Lima;Sul;Mouse;10;89,90;pago\n"
    b"20/01/2025;Carla Dias;Norte;Monitor;1;1.299,00;pendente\n"
    b"03/02/2025;Ana Souza;Norte;Teclado;3;150,00;pago\n"
    b"14/02/2025;Diego Melo;Leste;Cadeira;1;899,00;cancelado\n"
    b"28/02/2025;Bruno Lima;;Mouse;5;44,95;pago\n"
)

SCHEMA = [
    ColumnSpec(name="data_venda", data_type="date", format="%d/%m/%Y"),
    ColumnSpec(name="vendedor", data_type="text"),
    ColumnSpec(name="equipe", data_type="text"),
    ColumnSpec(name="produto", data_type="text"),
    ColumnSpec(name="quantidade", data_type="integer"),
    ColumnSpec(name="valor", data_type="decimal", scale=2),
    ColumnSpec(name="status", data_type="text"),
]


def bi_dataset(client: TestClient) -> tuple[str, str]:
    dataset = upload_csv(client, BI_CSV).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    job = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        json=import_payload(preview),
        headers=csrf(client),
    ).json()
    assert run_job(uuid.UUID(job["id"])) == "succeeded"
    detail = client.get(f"/api/v1/datasets/{dataset['id']}").json()
    types = {c["name"]: c["data_type"] for c in detail["columns"]}
    assert types == {c.name: c.data_type.value for c in SCHEMA}
    return dataset["id"], detail["current_version_id"]


def _analytics(client: TestClient, ds: str, **body: Any) -> Any:
    return client.post(f"/api/v1/datasets/{ds}/analytics", json=body, headers=csrf(client))


def test_kpis_use_the_chosen_measures(client: TestClient) -> None:
    register(client)
    ds, version = bi_dataset(client)
    response = _analytics(
        client,
        ds,
        metrics=[
            {"aggregation": "count"},
            {"aggregation": "sum", "column": "valor"},
            {"aggregation": "avg", "column": "valor"},
            {"aggregation": "min", "column": "data_venda"},
            {"aggregation": "max", "column": "valor"},
            {"aggregation": "count_distinct", "column": "vendedor"},
        ],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version_id"] == version
    assert body["version_number"] == 1
    assert body["matched_rows"] == 6
    # Decimais voltam como texto; a média ganha duas casas além da escala da coluna.
    assert body["rows"] == [
        {
            "key": None,
            "values": [6, "7082.75", "1180.4583", "2025-01-05", "4599.90", 4],
            "previous": None,
        }
    ]
    types = [(m["label"], m["data_type"], m["scale"]) for m in body["metrics"]]
    assert types == [
        ("Registros", "integer", None),
        ("Soma de valor", "decimal", 2),
        ("Média de valor", "decimal", 4),
        ("Mínimo de data_venda", "date", None),
        ("Máximo de valor", "decimal", 2),
        ("Distintos de vendedor", "integer", None),
    ]


def test_grouping_keeps_nulls_and_summarizes_the_rest(client: TestClient) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    top = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "sum", "column": "valor"}],
        dimension={"column": "equipe"},
        limit=2,
    ).json()
    assert [(r["key"], r["values"]) for r in top["rows"]] == [
        ("Norte", ["6048.90"]),
        ("Leste", ["899.00"]),
    ]
    assert top["total_groups"] == 4
    # "Outros" é calculado sobre os registros fora dos grupos mostrados (Sul e sem equipe).
    assert top["others"] == {"groups": 2, "values": ["134.85"], "previous": None}

    everything = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "count"}],
        dimension={"column": "equipe"},
        sort="dimension",
    ).json()
    assert [(r["key"], r["values"][0]) for r in everything["rows"]] == [
        ("Leste", 1),
        ("Norte", 3),
        ("Sul", 1),
        (None, 1),
    ]
    assert everything["others"] is None


def test_time_series_by_granularity(client: TestClient) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    monthly = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "sum", "column": "quantidade"}],
        dimension={"column": "data_venda", "granularity": "month"},
        # Ordenação pedida é ignorada: séries saem em ordem cronológica.
        sort="metric",
        direction="desc",
    ).json()
    assert [(r["key"], r["values"]) for r in monthly["rows"]] == [
        ("2025-01-01", [13]),
        ("2025-02-01", [9]),
    ]
    assert monthly["dimension"] == {
        "column": "data_venda",
        "data_type": "date",
        "granularity": "month",
    }
    weekly = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "count"}],
        dimension={"column": "data_venda", "granularity": "week"},
    ).json()
    # Semanas começam na segunda-feira: 05/01/2025 é domingo e cai na semana de 30/12/2024.
    assert weekly["rows"][0] == {"key": "2024-12-30", "values": [1], "previous": None}
    assert len(weekly["rows"]) == 6


def test_period_comparison(client: TestClient) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    february = {"column": "data_venda", "start": "2025-02-01", "end": "2025-02-28"}
    kpi = _analytics(
        client, ds, metrics=[{"aggregation": "sum", "column": "valor"}], comparison=february
    ).json()
    assert kpi["rows"][0]["values"] == ["1093.95"]
    # Período anterior com a mesma duração (28 dias): 04/01 a 31/01.
    assert kpi["rows"][0]["previous"] == ["5988.80"]
    assert kpi["matched_rows"] == 3
    assert kpi["comparison"] == {
        "column": "data_venda",
        "mode": "previous_period",
        "current_start": "2025-02-01",
        "current_end": "2025-02-28",
        "previous_start": "2025-01-04",
        "previous_end": "2025-01-31",
        "previous_rows": 3,
    }
    by_seller = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "count"}],
        dimension={"column": "vendedor"},
        comparison=february,
    ).json()
    pairs = {r["key"]: (r["values"][0], r["previous"][0]) for r in by_seller["rows"]}
    assert pairs == {
        "Ana Souza": (1, 1),
        "Bruno Lima": (1, 1),
        "Diego Melo": (1, 0),
        "Carla Dias": (0, 1),
    }
    last_year = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "sum", "column": "valor"}],
        comparison={**february, "mode": "previous_year"},
    ).json()
    # Sem dados em 2024: a soma anterior é nula, não zero.
    assert last_year["rows"][0]["previous"] == [None]
    assert last_year["comparison"]["previous_start"] == "2024-02-01"
    assert last_year["comparison"]["previous_rows"] == 0


def test_filters_are_typed_and_combined(client: TestClient) -> None:
    register(client)
    ds, version = bi_dataset(client)
    body = _analytics(
        client,
        ds,
        version_id=version,
        metrics=[{"aggregation": "count"}, {"aggregation": "sum", "column": "valor"}],
        filters=[
            {"column": "status", "operator": "in", "values": ["pago"]},
            {
                "column": "data_venda",
                "operator": "between",
                "value": "2025-01-01",
                "value_to": "2025-01-31",
            },
        ],
    ).json()
    assert body["rows"][0]["values"] == [2, "4689.80"]  # Ana (4.599,90) e Bruno (89,90)
    ranged = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "count"}],
        filters=[{"column": "valor", "operator": "between", "value": "100", "value_to": "1000"}],
    ).json()
    assert ranged["rows"][0]["values"] == [2]  # Teclado (150,00) e Cadeira (899,00)
    # Grupos extras (filtros gerais de um dashboard, filtros da tela) entram com E, cada um
    # com o próprio E/OU: vendas pagas do Sul ou sem equipe.
    grouped = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "count"}],
        filters=[{"column": "status", "operator": "eq", "value": "pago"}],
        extra_filters=[
            {
                "match": "any",
                "filters": [
                    {"column": "equipe", "operator": "eq", "value": "Sul"},
                    {"column": "equipe", "operator": "is_null"},
                ],
            }
        ],
    ).json()
    assert grouped["rows"][0]["values"] == [2]


@pytest.mark.parametrize(
    ("spec", "code"),
    [
        ({"metrics": [{"aggregation": "sum", "column": "vendedor"}]}, "invalid_metric"),
        ({"metrics": [{"aggregation": "avg"}]}, "invalid_metric"),
        ({"metrics": [{"aggregation": "max", "column": 'x"; DROP TABLE t; --'}]}, "invalid_metric"),
        (
            {"metrics": [{"aggregation": "count"}], "dimension": {"column": "valor"}},
            "invalid_dimension",
        ),
        (
            {
                "metrics": [{"aggregation": "count"}],
                "dimension": {"column": "status", "granularity": "month"},
            },
            "invalid_dimension",
        ),
        (
            {
                "metrics": [{"aggregation": "count"}],
                "comparison": {"column": "status", "start": "2025-01-01", "end": "2025-01-31"},
            },
            "invalid_comparison",
        ),
        (
            {
                "metrics": [{"aggregation": "count"}],
                "dimension": {"column": "data_venda"},
                "comparison": {"column": "data_venda", "start": "2025-01-01", "end": "2025-01-31"},
            },
            "invalid_comparison",
        ),
        (
            {
                "metrics": [{"aggregation": "count"}],
                "filters": [{"column": "valor", "operator": "contains", "value": "1"}],
            },
            "invalid_filter",
        ),
    ],
)
def test_plan_rejects_invalid_queries(spec: dict[str, Any], code: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        plan_aggregate(AggregateSpec.model_validate(spec), SCHEMA)
    assert error.value.code == code


@pytest.mark.parametrize(
    "body",
    [
        {"metrics": []},
        {"metrics": [{"aggregation": "count"}] * 7},
        {"metrics": [{"aggregation": "median", "column": "valor"}]},
        {"metrics": [{"aggregation": "count"}], "limit": 101},
        {
            "metrics": [{"aggregation": "count"}],
            "dimension": {"column": "data_venda", "granularity": "hour"},
        },
        {
            "metrics": [{"aggregation": "count"}],
            "comparison": {"column": "data_venda", "start": "2025-02-01", "end": "2025-01-01"},
        },
        {"metrics": [{"aggregation": "count"}], "sql": "SELECT 1"},
    ],
)
def test_api_rejects_out_of_allowlist_requests(client: TestClient, body: dict[str, Any]) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    response = _analytics(client, ds, **body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_long_series_ask_for_a_larger_granularity(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    ds, _ = bi_dataset(client)
    monkeypatch.setattr(aggregate, "MAX_POINTS", 1)
    response = _analytics(
        client,
        ds,
        metrics=[{"aggregation": "count"}],
        dimension={"column": "data_venda", "granularity": "month"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_points"
    assert "mês" in response.json()["error"]["message"]


def test_other_workspace_cannot_query_analytics(client: TestClient) -> None:
    register(client, workspace="Empresa A")
    ds, version = bi_dataset(client)
    intruder = new_client()
    register(intruder, workspace="Empresa B")
    body = {"version_id": version, "metrics": [{"aggregation": "count"}]}
    response = intruder.post(f"/api/v1/datasets/{ds}/analytics", json=body, headers=csrf(intruder))
    assert response.status_code == 404
