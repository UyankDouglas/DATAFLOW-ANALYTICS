"""Escrita de CSV e XLSX: formatos e proteção contra formula injection."""

import datetime as dt
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.processing.export_writers import ExportColumn, neutralize, write_csv, write_xlsx
from app.processing.types import DataType

COLUMNS = [
    ExportColumn("produto", DataType.TEXT),
    ExportColumn("valor", DataType.DECIMAL, 2),
    ExportColumn("data_venda", DataType.DATE),
    ExportColumn("pago", DataType.BOOLEAN),
    ExportColumn("quantidade", DataType.INTEGER),
]
ROWS = [
    [
        '=HYPERLINK("http://exemplo.invalid","clique")',
        Decimal("-1234.50"),
        dt.date(2025, 1, 5),
        True,
        -3,
    ],
    ["Mouse", Decimal("89.90"), None, False, 10],
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+5511999999999", "'+5511999999999"),
        ("-2", "'-2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tcmd", "'\tcmd"),
        ("\rcmd", "'\rcmd"),
        ("＝1+1", "'＝1+1"),  # sinal de igual de largura total
        ("Monitor", "Monitor"),
        ("a=b", "a=b"),
        ("", ""),
    ],
)
def test_neutralize_prefixes_formula_triggers(text: str, expected: str) -> None:
    assert neutralize(text) == expected


def test_csv_for_brazilian_excel(tmp_path: Path) -> None:
    path = tmp_path / "vendas.csv"
    assert write_csv(path, COLUMNS, ROWS, "excel_br") == 2
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM: o Excel reconhece UTF-8
    lines = raw.decode("utf-8-sig").splitlines()
    assert lines == [
        "produto;valor;data_venda;pago;quantidade",
        '"\'=HYPERLINK(""http://exemplo.invalid"",""clique"")";-1234,50;05/01/2025;Sim;-3',
        "Mouse;89,90;;Não;10",
    ]


def test_csv_standard(tmp_path: Path) -> None:
    path = tmp_path / "vendas.csv"
    write_csv(path, COLUMNS, ROWS[1:], "padrao")
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert path.read_text(encoding="utf-8").splitlines() == [
        "produto,valor,data_venda,pago,quantidade",
        "Mouse,89.90,,false,10",
    ]


def test_xlsx_never_contains_formulas(tmp_path: Path) -> None:
    path = tmp_path / "vendas.xlsx"
    rows = [*ROWS, ["texto\x01com controle", Decimal("0.10"), dt.date(2025, 3, 1), None, 1]]
    assert write_xlsx(path, COLUMNS, rows, "vendas: 2025/jan") == 3
    xml = zipfile.ZipFile(path).read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in xml
    sheet = load_workbook(path).active
    assert sheet is not None
    assert sheet.title == "vendas_ 2025_jan"
    first = next(iter(sheet.iter_rows(min_row=2, max_row=2)))
    assert (first[0].value, first[0].data_type) == (
        '\'=HYPERLINK("http://exemplo.invalid","clique")',
        "s",
    )
    # Números negativos continuam números; datas e booleanos saem tipados.
    assert (first[1].value, first[1].number_format) == (-1234.5, "#,##0.00")
    assert first[2].number_format == "DD/MM/YYYY"
    assert first[3].value is True
    assert first[4].value == -3
    third = next(iter(sheet.iter_rows(min_row=4, max_row=4)))
    assert third[0].value == "textocom controle"  # caractere de controle removido
