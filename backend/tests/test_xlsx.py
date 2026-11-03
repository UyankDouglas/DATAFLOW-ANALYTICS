import datetime as dt
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from app.processing.inspection import FileRejected
from app.processing.pipeline import run_xlsx_pipeline
from app.processing.reader import HeaderMismatch
from app.processing.types import ColumnConfig, DataType, ParseOptions
from app.processing.xlsx import XlsxLimits, inspect_xlsx, parse_xlsx_sample
from tests.xlsx_factory import (
    Blank,
    Date,
    ExcelError,
    Formula,
    build_xlsx,
    fake_encrypted,
    fake_legacy_xls,
    zip_bomb,
)

LIMITS = XlsxLimits(max_uncompressed_bytes=50 * 1024 * 1024, max_entries=500, max_ratio=200)

SALES = [
    ["data", "vendedor", "valor", "qtd", "total"],
    [Date(dt.datetime(2025, 1, 31)), "Ana", 1234.56, 2, Formula("C2*D2", 2469.12)],
    [Date(dt.datetime(2025, 2, 1)), "Bia", 10.5, 3, Formula("C3*D3")],  # fórmula sem valor salvo
    [None, None, None, None, None],  # vazia entre registros: registro rejeitado
    [Date(dt.datetime(2025, 2, 2)), "Cid", ExcelError(), 1, 0],
    [Date(dt.datetime(2025, 2, 3)), "Di", 7, 1, 7, "sobra"],  # campo a mais
]


def write(tmp_path: Path, data: bytes, name: str = "planilha.xlsx") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_inspect_lists_sheets_and_detects_header_below_title(tmp_path: Path) -> None:
    data = build_xlsx(
        {
            "Resumo": [["Relatório"], [], ["data", "valor"], [Date(dt.datetime(2025, 1, 1)), 5]],
            "Outra": [["x"]],
        }
    )
    info = inspect_xlsx(write(tmp_path, data), LIMITS)
    assert [s["name"] for s in info["sheets"]] == ["Resumo", "Outra"]
    assert info["default_sheet"] == "Resumo"
    assert info["header_row"] == 3  # o título na linha 1 não é o cabeçalho


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (fake_encrypted(), "xlsx_encrypted"),
        (fake_legacy_xls(), "xlsx_legacy_format"),
        (b"isto nao e um zip", "xlsx_invalid"),
        (b"PK\x03\x04" + b"\0" * 100, "xlsx_invalid"),
    ],
)
def test_inspect_rejects_unsafe_or_invalid_files(tmp_path: Path, payload: bytes, code: str) -> None:
    with pytest.raises(FileRejected) as error:
        inspect_xlsx(write(tmp_path, payload), LIMITS)
    assert error.value.code == code


def test_inspect_rejects_zip_bomb_by_declared_size(tmp_path: Path) -> None:
    with pytest.raises(FileRejected) as error:
        inspect_xlsx(write(tmp_path, zip_bomb(declared_mb=60)), LIMITS)
    assert error.value.code == "xlsx_decompression_limit"


def test_inspect_rejects_abnormal_compression_ratio(tmp_path: Path) -> None:
    generous = XlsxLimits(max_uncompressed_bytes=500 * 1024 * 1024, max_entries=500, max_ratio=200)
    with pytest.raises(FileRejected) as error:
        inspect_xlsx(write(tmp_path, zip_bomb(declared_mb=20)), generous)
    assert error.value.code == "xlsx_decompression_limit"


def test_inspect_rejects_macros_and_too_many_entries(tmp_path: Path) -> None:
    with_macro = build_xlsx({"A": [["x"]]}, extra_entries={"xl/vbaProject.bin": b"macro"})
    with pytest.raises(FileRejected) as error:
        inspect_xlsx(write(tmp_path, with_macro), LIMITS)
    assert error.value.code == "xlsx_macros"

    many = build_xlsx({"A": [["x"]]}, extra_entries={f"xl/media/{i}.bin": b"x" for i in range(20)})
    with pytest.raises(FileRejected) as error:
        inspect_xlsx(write(tmp_path, many, "b.xlsx"), XlsxLimits(10**9, 10, 200))
    assert error.value.code == "xlsx_too_complex"


def test_missing_workbook_part_is_invalid(tmp_path: Path) -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    with pytest.raises(FileRejected) as error:
        inspect_xlsx(write(tmp_path, buffer.getvalue()), LIMITS)
    assert error.value.code == "xlsx_invalid"


def test_sample_detects_range_offsets_and_issues(tmp_path: Path) -> None:
    rows = [["título do relatório"], [], *SALES, [Blank()], [Blank()]]
    path = write(tmp_path, build_xlsx({"Vendas": rows}, offsets={"Vendas": (1, 2)}))
    sample = parse_xlsx_sample(path, ParseOptions(sheet="Vendas", header_row=3), max_rows=100)
    assert sample.table.header == ["data", "vendedor", "valor", "qtd", "total"]
    assert sample.layout.first_column == 2
    assert sample.data_range.startswith("B3:F")
    assert sample.table.rows[0] == ["2025-01-31", "Ana", "1234.56", "2", "2469.12"]
    assert sample.cell_issues == 2  # fórmula sem valor + erro do Excel
    assert sample.table.ragged_rows == 1
    assert sample.table.empty_rows == 1  # a vazia entre registros; as do fim não contam
    assert sample.table.complete


def test_unknown_sheet_is_reported(tmp_path: Path) -> None:
    path = write(tmp_path, build_xlsx({"Vendas": SALES}))
    with pytest.raises(FileRejected) as error:
        parse_xlsx_sample(path, ParseOptions(sheet="Inexistente"), max_rows=10)
    assert error.value.code == "xlsx_sheet_not_found"


def _columns() -> list[ColumnConfig]:
    return [
        ColumnConfig(
            position=0, source_name="data", name="data", data_type=DataType.DATE, format="%Y-%m-%d"
        ),
        ColumnConfig(position=1, source_name="vendedor", name="vendedor", data_type=DataType.TEXT),
        ColumnConfig(
            position=2, source_name="valor", name="valor", data_type=DataType.DECIMAL, scale=2
        ),
        ColumnConfig(position=3, source_name="qtd", name="qtd", data_type=DataType.INTEGER),
        ColumnConfig(
            position=4, source_name="total", name="total", data_type=DataType.DECIMAL, scale=2
        ),
    ]


def test_xlsx_pipeline_uses_cached_formulas_and_rejects_explicitly(tmp_path: Path) -> None:
    path = write(tmp_path, build_xlsx({"Vendas": [*SALES, [Blank()], [Blank(), Blank()]]}))
    result = run_xlsx_pipeline(
        path,
        tmp_path / "out",
        ParseOptions(sheet="Vendas"),
        _columns(),
        ["data", "vendedor", "valor", "qtd", "total"],
        first_column=1,
        batch_rows=2,
        on_progress=lambda _: None,
    )
    assert result.reconciliation["received"] == 5
    assert result.reconciliation["consistent"]
    assert result.rows_valid == 1
    assert dict(result.reasons) == {
        "formula_sem_valor": 1,
        "linha_vazia": 1,
        "erro_na_celula": 1,
        "campos_a_mais": 1,
    }
    assert any("linha(s) vazia(s) ao final" in w for w in result.warnings)
    valid = pq.read_table(result.data_path).to_pylist()
    assert str(valid[0]["total"]) == "2469.12"  # valor salvo da fórmula, nada calculado
    rejected = {r["__df_reason"]: r for r in pq.read_table(result.rejected_path).to_pylist()}
    assert rejected["formula_sem_valor"]["__df_column"] == "total"
    assert rejected["formula_sem_valor"]["__df_line"] == 3
    assert rejected["erro_na_celula"]["valor"] == "#DIV/0!"
    assert rejected["erro_na_celula"]["__df_category"] == "rejeitado"


def test_xlsx_pipeline_detects_header_change(tmp_path: Path) -> None:
    path = write(tmp_path, build_xlsx({"Vendas": SALES}))
    with pytest.raises(HeaderMismatch):
        run_xlsx_pipeline(
            path, tmp_path / "out", ParseOptions(sheet="Vendas"), _columns(),
            ["outra", "vendedor", "valor", "qtd", "total"], first_column=1, batch_rows=10,
            on_progress=lambda _: None,
        )  # fmt: skip


def test_truncated_sample_estimates_rows_without_reading_the_whole_sheet(tmp_path: Path) -> None:
    rows: list[list[object]] = [["n"], *[[i] for i in range(1, 51)]]
    # Sem <dimension>: a estimativa conta os elementos <row> do XML.
    sample = parse_xlsx_sample(write(tmp_path, build_xlsx({"Dados": rows})), ParseOptions(), 10)
    assert sample.table.truncated
    assert (sample.estimated_rows, sample.data_range) == (50, "A1:A51")

    # Com <dimension>, vale o que a planilha declara (lido antes dos dados).
    declared = build_xlsx({"Dados": rows}, dimensions={"Dados": "A1:A2001"})
    info = inspect_xlsx(write(tmp_path, declared, "d.xlsx"), LIMITS)
    assert info["sheets"][0]["declared_rows"] == 2001
    sample = parse_xlsx_sample(write(tmp_path, declared, "d.xlsx"), ParseOptions(), 10)
    assert sample.estimated_rows == 2000
