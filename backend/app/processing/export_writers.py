"""Escrita de exportações CSV e XLSX, protegida contra formula injection.

Texto que começa com caractere capaz de iniciar uma fórmula em planilhas (`=`, `+`, `-`, `@`,
tabulação, retorno de carro e as variantes de largura total) recebe um apóstrofo na frente, como
recomenda a OWASP. No XLSX, toda célula de texto é ainda gravada como texto explícito, nunca
como fórmula. Colunas numéricas, de data e booleanas saem tipadas, então um número negativo
continua número.
"""

import csv
import datetime as dt
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font

from app.processing.types import DataType

CsvStyle = Literal["padrao", "excel_br"]

FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r", "＝", "＋", "－", "＠")
PROGRESS_EVERY = 10_000

CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class ExportColumn:
    name: str
    data_type: DataType
    scale: int | None = None


def neutralize(text: str) -> str:
    """Impede que uma planilha interprete o texto como fórmula."""
    return "'" + text if text.startswith(FORMULA_TRIGGERS) else text


def _csv_value(value: Any, column: ExportColumn, style: CsvStyle) -> str:
    br = style == "excel_br"
    if value is None:
        return ""
    if isinstance(value, bool):
        return ("Sim" if value else "Não") if br else ("true" if value else "false")
    if isinstance(value, Decimal):
        text = format(value, "f")
        return text.replace(".", ",") if br else text
    if isinstance(value, float):
        text = repr(value)
        return text.replace(".", ",") if br else text
    if isinstance(value, int):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.strftime("%d/%m/%Y %H:%M:%S" if br else "%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.strftime("%d/%m/%Y" if br else "%Y-%m-%d")
    return neutralize(str(value))


def write_csv(
    path: Path,
    columns: Sequence[ExportColumn],
    rows: Iterable[Sequence[Any]],
    style: CsvStyle,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    """CSV padrão (vírgula, ponto decimal, datas ISO, UTF-8) ou para o Excel em português
    (ponto e vírgula, vírgula decimal, datas dd/mm/aaaa, UTF-8 com BOM). Devolve os registros."""
    br = style == "excel_br"
    count = 0
    with path.open("w", encoding="utf-8-sig" if br else "utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";" if br else ",", lineterminator="\r\n")
        writer.writerow([neutralize(c.name) for c in columns])
        for row in rows:
            writer.writerow(
                [
                    _csv_value(value, column, style)
                    for value, column in zip(row, columns, strict=True)
                ]
            )
            count += 1
            if on_progress and count % PROGRESS_EVERY == 0:
                on_progress(count)
    return count


def _number_format(column: ExportColumn) -> str | None:
    match column.data_type:
        case DataType.INTEGER:
            return "#,##0"
        case DataType.DECIMAL:
            scale = column.scale or 0
            return "#,##0" + ("." + "0" * scale if scale else "")
        case DataType.DATE:
            return "DD/MM/YYYY"
        case DataType.DATETIME:
            return "DD/MM/YYYY HH:MM:SS"
        case _:
            return None


def write_xlsx(
    path: Path,
    columns: Sequence[ExportColumn],
    rows: Iterable[Sequence[Any]],
    sheet_title: str,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    """Planilha em modo de escrita contínua (memória constante). Números, datas e booleanos
    saem tipados; texto sai sempre como texto. Devolve os registros escritos."""
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(title=_safe_sheet_title(sheet_title))
    bold = Font(bold=True)
    header = []
    for column in columns:
        cell = WriteOnlyCell(sheet, value=_clean_text(column.name))
        cell.data_type = "s"
        cell.font = bold
        header.append(cell)
    sheet.append(header)
    formats = [_number_format(c) for c in columns]
    count = 0
    for row in rows:
        cells: list[Any] = []
        for value, column, number_format in zip(row, columns, formats, strict=True):
            if value is None:
                cells.append(None)
                continue
            if isinstance(value, str) or column.data_type == DataType.TEXT:
                cell = WriteOnlyCell(sheet, value=_clean_text(str(value)))
                cell.data_type = "s"  # nunca fórmula, mesmo que o texto comece com "="
            else:
                cell = WriteOnlyCell(sheet, value=value)
                if number_format and not isinstance(value, bool):
                    cell.number_format = number_format
            cells.append(cell)
        sheet.append(cells)
        count += 1
        if on_progress and count % PROGRESS_EVERY == 0:
            on_progress(count)
    workbook.save(path)
    return count


def _clean_text(text: str) -> str:
    # Caracteres de controle não são permitidos no XML da planilha.
    return neutralize(ILLEGAL_CHARACTERS_RE.sub("", text))


def _safe_sheet_title(title: str) -> str:
    cleaned = "".join("_" if ch in "[]:*?/\\" else ch for ch in title).strip("'") or "Dados"
    return cleaned[:31]
