import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.conftest import SALES_CSV, csrf, register, upload_csv


def test_upload_stores_original_privately_with_random_key(client: TestClient, s3) -> None:
    register(client)
    response = upload_csv(client, SALES_CSV, "Vendas Janeiro.csv")
    assert response.status_code == 201, response.text
    body = response.json()
    upload = body["upload"]
    assert body["dataset"]["name"] == "Vendas Janeiro"
    assert body["dataset"]["status"] == "draft"
    assert upload["original_filename"] == "Vendas Janeiro.csv"
    assert upload["size_bytes"] == len(SALES_CSV)
    assert upload["detection"]["delimiter"] == ";"
    assert upload["detection"]["utf8_valid"] is True

    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="dataflow-test")["Contents"]]
    assert len(keys) == 1
    assert keys[0].endswith(f"/uploads/{upload['id']}/original")
    assert "Vendas" not in keys[0]


@pytest.mark.parametrize(
    ("filename", "content", "status", "code"),
    [
        ("planilha.xlsx", b"PK\x03\x04...", 415, "format_not_yet_supported"),
        ("script.exe", b"MZ...", 415, "unsupported_extension"),
        ("disfarcado.csv", b"PK\x03\x04conteudo-zip", 422, "content_mismatch"),
        ("imagem.csv", b"\x89PNG\r\n\x1a\nxxxx", 422, "content_mismatch"),
        ("vazio.csv", b"", 422, "empty_file"),
        ("utf16.csv", "a,b\n1,2\n".encode("utf-16"), 422, "unsupported_encoding"),
    ],
)
def test_invalid_uploads_are_rejected(
    client: TestClient, filename: str, content: bytes, status: int, code: str
) -> None:
    register(client)
    response = upload_csv(client, content, filename)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def test_upload_size_limit_is_enforced_while_streaming(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, s3
) -> None:
    register(client)
    monkeypatch.setattr(get_settings(), "max_csv_mb", 1)
    oversized = b"a,b\n" + b"1,2\n" * (300 * 1024)
    response = upload_csv(client, oversized, "grande.csv")
    assert response.status_code == 413
    assert "1 MB" in response.json()["error"]["message"]
    assert s3.list_objects_v2(Bucket="dataflow-test").get("KeyCount", 0) == 0
    assert not list(get_settings().temp_dir.glob("upload-*"))


def test_filename_is_sanitized(client: TestClient) -> None:
    register(client)
    response = upload_csv(client, SALES_CSV, "..%2F..%2Fetc%2Fpasswd.csv")
    assert response.status_code == 201
    assert response.json()["upload"]["original_filename"] == "passwd.csv"


def test_non_utf8_upload_requires_explicit_encoding(client: TestClient) -> None:
    register(client)
    content = "nome;cidade\nJoão;São Paulo\n".encode("cp1252")
    dataset = upload_csv(client, content, "latin.csv").json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview").json()
    assert preview["parse_options"]["encoding"] == "windows-1252"
    assert any("não é UTF-8" in w for w in preview["warnings"])
    assert preview["rows"][0] == ["João", "São Paulo"]

    forced_utf8 = client.post(
        f"/api/v1/datasets/{dataset['id']}/preview",
        json={**preview["parse_options"], "encoding": "utf-8"},
        headers=csrf(client),
    )
    assert forced_utf8.status_code == 422
    assert forced_utf8.json()["error"]["code"] == "encoding_mismatch"


def test_preview_returns_first_rows_types_and_stats(client: TestClient) -> None:
    register(client)
    dataset = upload_csv(client, SALES_CSV).json()["dataset"]
    preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert body["header"] == [
        "data_venda",
        "vendedor",
        "equipe",
        "produto",
        "quantidade",
        "valor",
        "status",
    ]
    assert body["column_count"] == 7
    assert len(body["rows"]) == 5
    types = {c["source_name"]: c["inferred_type"] for c in body["columns"]}
    assert types["data_venda"] == "date"
    assert types["valor"] == "decimal"
    assert types["quantidade"] == "text"  # contém "x" na amostra
    assert body["row_count"] == {
        "value": 6,
        "exact": True,
        "method": "arquivo lido por completo na pré-visualização",
    }
    assert body["ragged_rows_in_sample"] == 1
    assert body["empty_rows_in_sample"] == 1
    assert body["parse_options"]["decimal_separator"] == ","
