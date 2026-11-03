"""Gera XLSX mínimos escrevendo o XML diretamente.

Bibliotecas de escrita não gravam valor salvo de fórmulas nem permitem montar arquivos
malformados ou maliciosos; aqui cada caso é controlado explicitamente.
"""

import datetime as dt
import io
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape


@dataclass
class Formula:
    expression: str
    cached: object = None  # None = fórmula sem valor salvo


@dataclass
class ExcelError:
    code: str = "#DIV/0!"


@dataclass
class Blank:
    """Célula sem valor, só com estilo — o Excel grava assim linhas formatadas vazias."""


@dataclass
class Date:
    value: dt.datetime
    with_time: bool = False


Row = list[object]

EXCEL_EPOCH = dt.datetime(1899, 12, 30)


def _column(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _cell(ref: str, value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Blank):
        return f'<c r="{ref}" s="1"/>'
    if isinstance(value, Formula):
        cached = "" if value.cached is None else f"<v>{value.cached}</v>"
        return f'<c r="{ref}"><f>{escape(value.expression)}</f>{cached}</c>'
    if isinstance(value, ExcelError):
        return f'<c r="{ref}" t="e"><v>{value.code}</v></c>'
    if isinstance(value, Date):
        serial = (value.value - EXCEL_EPOCH).total_seconds() / 86400
        style = 2 if value.with_time else 1
        return f'<c r="{ref}" s="{style}"><v>{serial}</v></c>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, int | float):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return (
        f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'
    )


def _sheet(
    rows: list[Row], start_row: int = 1, start_col: int = 1, dimension: str | None = None
) -> str:
    body = []
    for r, row in enumerate(rows, start=start_row):
        cells = "".join(_cell(f"{_column(c)}{r}", v) for c, v in enumerate(row, start=start_col))
        if cells:
            body.append(f'<row r="{r}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + (f'<dimension ref="{dimension}"/>' if dimension else "")
        + f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="22" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    "</cellXfs></styleSheet>"
)


def build_xlsx(
    sheets: dict[str, list[Row]],
    *,
    offsets: dict[str, tuple[int, int]] | None = None,
    extra_entries: dict[str, bytes] | None = None,
    dimensions: dict[str, str] | None = None,
) -> bytes:
    offsets = offsets or {}
    dimensions = dimensions or {}
    names = list(sheets)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(names) + 1)
        )
        + "</Types>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(names, start=1)
        )
        + "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(names) + 1)
        )
        + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        + "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", STYLES)
        for i, name in enumerate(names, start=1):
            start_row, start_col = offsets.get(name, (1, 1))
            archive.writestr(
                f"xl/worksheets/sheet{i}.xml",
                _sheet(sheets[name], start_row, start_col, dimensions.get(name)),
            )
        for path, data in (extra_entries or {}).items():
            archive.writestr(path, data)
    return buffer.getvalue()


def zip_bomb(declared_mb: int = 300) -> bytes:
    """XLSX válido com uma entrada que descompacta em centenas de MB de zeros."""
    base = build_xlsx({"Dados": [["a"], [1]]})
    buffer = io.BytesIO(base)
    with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/media/padding.bin", b"\0" * (declared_mb * 1024 * 1024))
    return buffer.getvalue()


def fake_encrypted() -> bytes:
    """Cabeçalho OLE com o fluxo EncryptionInfo, como o Excel grava planilhas com senha."""
    return (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        + b"\0" * 504
        + "EncryptionInfo".encode("utf-16-le")
        + b"\0" * 1024
    )


def fake_legacy_xls() -> bytes:
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 2048
