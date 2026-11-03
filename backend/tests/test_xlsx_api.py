"""XLSX pela API: upload com validação de conteúdo, abas, mapeamento com obrigatoriedade e job."""

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import session_scope
from app.models import AuditLog
from app.services.job_runner import run_job
from tests.conftest import csrf, register, upload_csv
from tests.test_import_flow import import_payload
from tests.xlsx_factory import (
    Date,
    ExcelError,
    Formula,
    build_xlsx,
    fake_encrypted,
    fake_legacy_xls,
    zip_bomb,
)

WORKBOOK = build_xlsx(
    {
        "Vendas": [
            ["Relatório de vendas"],
            [],
            ["data", "vendedor", "valor", "qtd", "total"],
            [Date(dt.datetime(2025, 1, 31)), "Ana", 1234.56, 2, Formula("C4*D4", 2469.12)],
            [Date(dt.datetime(2025, 2, 1)), "Bia", 10.5, 3, Formula("C5*D5")],
            [Date(dt.datetime(2025, 2, 2)), "Cid", 7, None, ExcelError()],
            [Date(dt.datetime(2025, 2, 3)), None, 8, 1, 8],
        ],
        "Metas": [["vendedor", "meta"], ["Ana", 5000], ["Bia", 3000]],
    },
    offsets={"Metas": (3, 2)},  # dados começam em B3
)


def _upload(client: TestClient, content: bytes = WORKBOOK, name: str = "vendas.xlsx") -> Any:
    return upload_csv(client, content, name)


def _bucket_keys(s3: Any) -> list[str]:
    return [o["Key"] for o in s3.list_objects_v2(Bucket="dataflow-test").get("Contents", [])]


def test_xlsx_upload_lists_sheets_and_preview_detects_header(client: TestClient, s3: Any) -> None:
    register(client)
    response = _upload(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["dataset"]["source_format"] == "xlsx"
    assert body["upload"]["file_format"] == "xlsx"
    assert [s["name"] for s in body["upload"]["detection"]["sheets"]] == ["Vendas", "Metas"]
    assert len(_bucket_keys(s3)) == 1

    ds = body["dataset"]["id"]
    # A detecção pula o título acima da tabela; a linha também pode ser escolhida à mão.
    first = client.get(f"/api/v1/datasets/{ds}/preview").json()
    assert first["parse_options"]["sheet"] == "Vendas"
    assert first["parse_options"]["header_row"] == 3
    assert first["header"] == ["data", "vendedor", "valor", "qtd", "total"]
    manual = client.post(
        f"/api/v1/datasets/{ds}/preview",
        json={"sheet": "Vendas", "header_row": 1},
        headers=csrf(client),
    ).json()
    assert manual["header"] == ["Relatório de vendas"]
    assert manual["ragged_rows_in_sample"] == 5  # linhas 3 a 7 têm dados fora da coluna A

    preview = client.post(
        f"/api/v1/datasets/{ds}/preview",
        json={"sheet": "Vendas", "header_row": 3},
        headers=csrf(client),
    ).json()
    assert preview["source_format"] == "xlsx"
    assert preview["header"] == ["data", "vendedor", "valor", "qtd", "total"]
    assert preview["data_range"] == "A3:E7"
    assert preview["rows"][0] == ["2025-01-31", "Ana", "1234.56", "2", "2469.12"]
    assert preview["cell_issues_in_sample"] == 2  # fórmula sem valor salvo e #DIV/0!
    assert any("Fórmulas não são executadas" in w for w in preview["warnings"])
    assert preview["row_count"] == {
        "value": 4,
        "exact": True,
        "method": "arquivo lido por completo na pré-visualização",
    }
    types = {c["source_name"]: c["inferred_type"] for c in preview["columns"]}
    assert types["data"] == "date"
    assert types["valor"] == "decimal"

    other = client.post(
        f"/api/v1/datasets/{ds}/preview", json={"sheet": "Metas"}, headers=csrf(client)
    ).json()
    assert other["parse_options"]["header_row"] == 3
    assert other["first_column"] == 2
    assert other["data_range"] == "B3:C5"
    assert other["header"] == ["vendedor", "meta"]


def _import_vendas(client: TestClient, ds: str, **column_overrides: dict[str, Any]) -> dict:
    preview = client.post(
        f"/api/v1/datasets/{ds}/preview",
        json={"sheet": "Vendas", "header_row": 3},
        headers=csrf(client),
    ).json()
    payload = import_payload(preview, types={"qtd": "integer", "total": "decimal"})
    for column in payload["columns"]:
        column.update(column_overrides.get(column["source_name"], {}))
        if column["source_name"] == "total":
            column["scale"] = 2
    return client.post(f"/api/v1/datasets/{ds}/imports", json=payload, headers=csrf(client))


def test_xlsx_import_rejects_formulas_without_value_and_applies_mapping_rules(
    client: TestClient,
) -> None:
    register(client)
    ds = _upload(client).json()["dataset"]["id"]
    response = _import_vendas(
        client,
        ds,
        vendedor={"required": True},
        qtd={"fill_value": "0"},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["bytes_total"] is None  # XLSX: progresso por registros, sem percentual estimado
    assert job["config"]["first_column"] == 1
    assert job["config"]["parse_options"]["header_row"] == 3
    assert run_job(uuid.UUID(job["id"])) == "succeeded"

    done = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert (done["rows_total"], done["rows_valid"], done["rows_rejected"]) == (4, 1, 3)
    assert done["rejection_summary"]["by_reason"] == {
        "formula_sem_valor": 1,
        "erro_na_celula": 1,
        "campo_obrigatorio": 1,
    }
    detail = client.get(f"/api/v1/datasets/{ds}").json()
    version = detail["current_version"]
    assert version["reconciliation"]["consistent"] is True
    assert version["transformations"]["kind"] == "import"
    assert version["transformations"]["source_format"] == "xlsx"
    saved = {c["name"]: c for c in detail["columns"]}
    assert saved["vendedor"]["required"] is True
    assert saved["qtd"]["fill_value"] == "0"

    rows = client.get(f"/api/v1/datasets/{ds}/rows").json()
    assert rows["rows"] == [["2025-01-31", "Ana", "1234.56", 2, "2469.12"]]

    rejected = client.get(f"/api/v1/datasets/{ds}/versions/{version['id']}/rejected").json()
    assert rejected["total"] == 3
    reasons = {row[rejected["columns"].index("__df_reason")] for row in rejected["rows"]}
    assert reasons == {"formula_sem_valor", "erro_na_celula", "campo_obrigatorio"}


def test_invalid_fill_value_is_refused_before_processing(client: TestClient) -> None:
    register(client)
    ds = _upload(client).json()["dataset"]["id"]
    response = _import_vendas(client, ds, qtd={"fill_value": "muitos"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_fill_value"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (zip_bomb(20), "xlsx_decompression_limit"),
        (fake_encrypted(), "xlsx_encrypted"),
        (fake_legacy_xls(), "xlsx_legacy_format"),
        (
            build_xlsx({"Dados": [["a"], [1]]}, extra_entries={"xl/vbaProject.bin": b"\0" * 64}),
            "xlsx_macros",
        ),
        (b"PK\x03\x04" + b"\0" * 200, "xlsx_invalid"),
    ],
)
def test_malicious_xlsx_is_refused_and_never_stored(
    client: TestClient, s3: Any, payload: bytes, code: str
) -> None:
    register(client)
    response = _upload(client, payload, "suspeito.xlsx")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code
    assert _bucket_keys(s3) == []
    with session_scope() as db:
        events = db.scalars(
            select(AuditLog).where(AuditLog.action == "dataset.upload_rejected")
        ).all()
        assert [e.details["reason"] for e in events] == [code]


def test_xlsx_size_limit_is_enforced(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    register(client)
    monkeypatch.setattr(get_settings(), "max_xlsx_mb", 0)
    response = _upload(client)
    assert response.status_code == 413
    assert "XLSX" in response.json()["error"]["message"]


def test_other_sheet_becomes_independent_dataset(client: TestClient, s3: Any) -> None:
    register(client)
    ds = _upload(client).json()["dataset"]["id"]
    response = client.post(
        f"/api/v1/datasets/{ds}/sheets", json={"sheet": "Metas"}, headers=csrf(client)
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["dataset"]["name"] == "vendas - Metas"
    assert created["dataset"]["id"] != ds
    assert len(_bucket_keys(s3)) == 2  # cópia própria: datasets não compartilham objetos

    preview = client.get(f"/api/v1/datasets/{created['dataset']['id']}/preview").json()
    assert preview["parse_options"]["sheet"] == "Metas"
    assert preview["header"] == ["vendedor", "meta"]

    missing = client.post(
        f"/api/v1/datasets/{ds}/sheets", json={"sheet": "Inexistente"}, headers=csrf(client)
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "xlsx_sheet_not_found"
