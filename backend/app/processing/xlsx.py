"""Leitura segura de XLSX: inspeção no recebimento, amostra para a pré-visualização e lotes.

Regras:
- Nada é executado: macros fazem o arquivo ser recusado e fórmulas nunca são calculadas.
  Fórmula com valor salvo usa esse valor; fórmula sem valor salvo rejeita o registro com o
  motivo `formula_sem_valor`, em vez de virar uma célula vazia.
- O XML é lido com defusedxml (ativado automaticamente pelo openpyxl quando instalado).
- Antes de abrir a planilha, o diretório do ZIP é conferido: quantidade de entradas, tamanho
  descompactado total e taxa de compressão. O `zipfile` nunca descompacta além do tamanho
  declarado de cada entrada (e confere o CRC), então esses limites valem de fato.
- Planilhas criptografadas (contêiner OLE com EncryptionInfo) e XLS legado são recusados.
- Números do Excel são ponto flutuante (IEEE 754); o texto usado é a menor representação
  decimal que reproduz o valor armazenado, sem acumular erro de conversão.
"""

import datetime as dt
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.xml.constants import SHEET_MAIN_NS
from openpyxl.xml.functions import iterparse

from app.processing.inspection import FileRejected, SampleTable
from app.processing.reader import (
    CellIssue,
    HeaderMismatch,
    RawBatch,
    StructuralError,
    build_raw_frame,
)
from app.processing.types import ParseOptions

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"
_ENCRYPTION_MARKERS = (
    "EncryptionInfo".encode("utf-16-le"),
    "EncryptedPackage".encode("utf-16-le"),
)
HEADER_SCAN_ROWS = 50
_DIMENSION_TAG = f"{{{SHEET_MAIN_NS}}}dimension"
_SHEET_DATA_TAG = f"{{{SHEET_MAIN_NS}}}sheetData"
_ROW_TAG = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?row[\s/>]")


def _declared_size(sheet: Any) -> None:
    """Dimensão declarada da aba, lendo o XML só até o início dos dados.

    O openpyxl original só percebe a falta de `<dimension>` no fim de `<sheetData>`, isto é,
    depois de interpretar a aba inteira — e faz isso com todas as abas ao abrir a planilha.
    Planilhas sem essa tag (comuns quando geradas por bibliotecas) levavam dezenas de segundos
    para abrir. Aqui a leitura para no primeiro elemento de dados.
    """
    with sheet._get_source() as source:
        for _event, element in iterparse(source, events=("start",)):
            if element.tag == _DIMENSION_TAG:
                try:
                    bounds = range_boundaries(element.get("ref") or "")
                except (TypeError, ValueError):
                    return
                if None not in bounds:
                    sheet._min_column, sheet._min_row, sheet._max_column, sheet._max_row = bounds
                return
            if element.tag == _SHEET_DATA_TAG:
                return


# Substitui o dimensionamento das abas em modo somente leitura (mesmo resultado, sem ler os dados).
setattr(ReadOnlyWorksheet, "_get_size", _declared_size)  # noqa: B010


def _count_xml_rows(sheet: Any) -> int:
    """Elementos `<row>` no XML da aba, sem interpretar células (estimativa barata)."""
    count = 0
    tail = b""
    with sheet._get_source() as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            data = tail + chunk
            # Ocorrências inteiramente dentro do trecho repetido já foram contadas.
            count += len(_ROW_TAG.findall(data)) - len(_ROW_TAG.findall(tail))
            tail = data[-32:]
    return count


_TIME_TOKENS = re.compile(r"[hs]", re.IGNORECASE)
_FORMAT_NOISE = re.compile(r'"[^"]*"|\[[^\]]*\]|\\.')


@dataclass(frozen=True)
class XlsxLimits:
    max_uncompressed_bytes: int
    max_entries: int
    max_ratio: int


@dataclass
class SheetLayout:
    header_row: int
    first_column: int  # 1 = coluna A
    last_column: int


@dataclass
class XlsxSample:
    table: SampleTable
    sheet: str
    sheets: list[dict[str, Any]]
    layout: SheetLayout
    data_range: str
    cell_issues: int
    estimated_rows: int | None


@dataclass
class _Cell:
    text: str
    issue: str | None = None


@dataclass
class _RowReader:
    """Percorre a mesma aba lida duas vezes: valores salvos e fórmulas."""

    values: Iterator[tuple[Any, ...]]
    formulas: Iterator[tuple[Any, ...]]
    start_row: int
    _row: int = field(init=False)

    def __post_init__(self) -> None:
        self._row = self.start_row - 1

    def __iter__(self) -> "_RowReader":
        return self

    def __next__(self) -> tuple[int, list[_Cell]]:
        value_cells = next(self.values)
        formula_cells = next(self.formulas, ())
        self._row += 1
        cells = [
            cell_text(value, formula_cells[i] if i < len(formula_cells) else None)
            for i, value in enumerate(value_cells)
        ]
        return self._row, cells


def column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _has_time(number_format: str | None) -> bool:
    if not number_format:
        return False
    return bool(_TIME_TOKENS.search(_FORMAT_NOISE.sub("", number_format)))


def _number_text(value: int | float) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value.is_integer() and abs(value) < 2**53:
        return str(int(value))
    return repr(value)


def cell_text(value_cell: Any, formula_cell: Any) -> _Cell:
    """Texto canônico da célula e eventual problema (fórmula sem valor, erro do Excel)."""
    value = getattr(value_cell, "value", None)
    if (
        formula_cell is not None
        and getattr(formula_cell, "data_type", None) == "f"
        and value is None
    ):
        return _Cell("", CellIssue.FORMULA_WITHOUT_VALUE)
    if getattr(value_cell, "data_type", None) == "e":
        return _Cell(str(value), CellIssue.CELL_ERROR)
    if value is None:
        return _Cell("")
    if isinstance(value, bool):
        return _Cell("true" if value else "false")
    if isinstance(value, int | float):
        return _Cell(_number_text(value))
    if isinstance(value, dt.datetime):
        if value.time() != dt.time(0) or _has_time(getattr(value_cell, "number_format", None)):
            return _Cell(value.strftime("%Y-%m-%d %H:%M:%S"))
        return _Cell(value.strftime("%Y-%m-%d"))
    if isinstance(value, dt.date):
        return _Cell(value.strftime("%Y-%m-%d"))
    if isinstance(value, dt.time):
        return _Cell(value.strftime("%H:%M:%S"))
    return _Cell(str(value))


def check_container(path: Path, limits: XlsxLimits) -> None:
    with path.open("rb") as handle:
        head = handle.read(8)
    if head.startswith(OLE_MAGIC):
        if _contains_marker(path):
            raise FileRejected(
                "A planilha está protegida por senha (criptografada). Remova a proteção e envie novamente.",
                "xlsx_encrypted",
            )
        raise FileRejected(
            "O arquivo está no formato Excel legado (XLS), que não é aceito. Salve como .xlsx.",
            "xlsx_legacy_format",
        )
    if not head.startswith(ZIP_MAGIC):
        raise FileRejected("O arquivo não é uma planilha XLSX válida.", "xlsx_invalid")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise FileRejected("O arquivo XLSX está corrompido ou malformado.", "xlsx_invalid") from exc
    if len(infos) > limits.max_entries:
        raise FileRejected(
            f"O XLSX tem {len(infos)} arquivos internos; o limite é {limits.max_entries}.",
            "xlsx_too_complex",
        )
    total = sum(info.file_size for info in infos)
    if total > limits.max_uncompressed_bytes:
        raise FileRejected(
            "O conteúdo descompactado do XLSX excede o limite permitido "
            f"({limits.max_uncompressed_bytes // (1024 * 1024)} MB).",
            "xlsx_decompression_limit",
        )
    for info in infos:
        if info.flag_bits & 0x1:
            raise FileRejected(
                "O XLSX contém partes criptografadas e não pode ser lido.", "xlsx_encrypted"
            )
        ratio = info.file_size / max(info.compress_size, 1)
        if info.file_size > 1024 * 1024 and ratio > limits.max_ratio:
            raise FileRejected(
                "O XLSX tem taxa de compressão anormal (possível arquivo malicioso).",
                "xlsx_decompression_limit",
            )
    names = {info.filename for info in infos}
    if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
        raise FileRejected("O arquivo não é uma planilha XLSX válida.", "xlsx_invalid")
    if any(name.lower().endswith("vbaproject.bin") for name in names):
        raise FileRejected(
            "A planilha contém macros, que não são aceitas. Salve como .xlsx sem macros.",
            "xlsx_macros",
        )


def _contains_marker(path: Path) -> bool:
    overlap = max(len(marker) for marker in _ENCRYPTION_MARKERS)
    previous = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            window = previous + chunk
            if any(marker in window for marker in _ENCRYPTION_MARKERS):
                return True
            previous = chunk[-overlap:]
    return False


def _open(path: Path, *, data_only: bool) -> Workbook:
    try:
        return load_workbook(path, read_only=True, data_only=data_only, keep_links=False)
    except Exception as exc:  # openpyxl levanta tipos variados para arquivos malformados
        raise FileRejected(
            "Não foi possível ler a planilha: arquivo malformado.", "xlsx_invalid"
        ) from exc


def _row_values(cells: tuple[Any, ...]) -> list[_Cell]:
    return [cell_text(cell, None) for cell in cells]


def _filled(cells: list[_Cell]) -> list[int]:
    return [i for i, cell in enumerate(cells, start=1) if cell.text.strip() or cell.issue]


def detect_layout(rows: Iterator[tuple[int, list[_Cell]]], header_row: int | None) -> SheetLayout:
    """Linha do cabeçalho e colunas ocupadas.

    Com a linha informada, usa essa linha. Sem ela, examina as primeiras linhas da aba e escolhe
    a primeira "larga" — com mais da metade das colunas da tabela preenchidas —, o que pula
    títulos e notas acima do cabeçalho (ex.: "Relatório de vendas" na linha 1).
    """
    if header_row is not None:
        for row_number, cells in rows:
            if row_number < header_row:
                continue
            filled = _filled(cells)
            if row_number > header_row or not filled:
                break
            return SheetLayout(
                header_row=row_number, first_column=filled[0], last_column=filled[-1]
            )
        return SheetLayout(header_row=header_row, first_column=1, last_column=0)

    scanned: list[tuple[int, list[int]]] = []
    for row_number, cells in rows:
        if row_number > HEADER_SCAN_ROWS:
            break
        filled = _filled(cells)
        if filled:
            scanned.append((row_number, filled))
    if not scanned:
        return SheetLayout(header_row=1, first_column=1, last_column=0)
    widest = max(len(filled) for _, filled in scanned)
    row_number, filled = next((r, f) for r, f in scanned if len(f) * 2 > widest)
    return SheetLayout(header_row=row_number, first_column=filled[0], last_column=filled[-1])


def inspect_xlsx(path: Path, limits: XlsxLimits) -> dict[str, Any]:
    check_container(path, limits)
    workbook = _open(path, data_only=True)
    try:
        sheets = [
            {
                "name": sheet.title,
                "hidden": sheet.sheet_state != "visible",
                "declared_rows": sheet.max_row,
                "declared_columns": sheet.max_column,
            }
            for sheet in workbook.worksheets
        ]
        if not sheets:
            raise FileRejected("A planilha não contém abas de dados.", "xlsx_no_sheets")
        visible = [ws for ws in workbook.worksheets if ws.sheet_state == "visible"]
        worksheet = (visible or workbook.worksheets)[0]
        default = worksheet.title
        worksheet.reset_dimensions()
        layout = detect_layout(
            ((i, _row_values(r)) for i, r in enumerate(worksheet.iter_rows(), start=1)), None
        )
    except FileRejected:
        raise
    except Exception as exc:
        raise FileRejected(
            "Não foi possível ler a planilha: arquivo malformado.", "xlsx_invalid"
        ) from exc
    finally:
        workbook.close()
    return {
        "format": "xlsx",
        "sheets": sheets,
        "default_sheet": default,
        "header_row": layout.header_row,
    }


class _Workbooks:
    """Mesma aba aberta duas vezes em modo somente leitura (valores e fórmulas)."""

    def __init__(self, path: Path, sheet: str | None) -> None:
        self.values = _open(path, data_only=True)
        self.formulas = _open(path, data_only=False)
        name = sheet or self.values.worksheets[0].title
        if name not in self.values.sheetnames:
            self.close()
            raise FileRejected(f"A aba '{name}' não existe na planilha.", "xlsx_sheet_not_found")
        self.sheet = name
        self.sheets = [
            {
                "name": ws.title,
                "hidden": ws.sheet_state != "visible",
                "declared_rows": ws.max_row,
                "declared_columns": ws.max_column,
            }
            for ws in self.values.worksheets
        ]

    def rows(self, start_row: int) -> _RowReader:
        value_sheet = self.values[self.sheet]
        formula_sheet = self.formulas[self.sheet]
        value_sheet.reset_dimensions()
        formula_sheet.reset_dimensions()
        return _RowReader(
            values=value_sheet.iter_rows(min_row=start_row),
            formulas=formula_sheet.iter_rows(min_row=start_row),
            start_row=start_row,
        )

    def close(self) -> None:
        self.values.close()
        self.formulas.close()


def _span(
    cells: list[_Cell], layout: SheetLayout, width: int
) -> tuple[list[str], int, str | None, int | None]:
    """Valores dentro das colunas do cabeçalho, campos fora delas e o primeiro problema."""
    start = layout.first_column - 1
    inside = cells[start : start + width]
    texts = [cell.text for cell in inside] + [""] * (width - len(inside))
    outside = sum(
        1
        for i, cell in enumerate(cells)
        if (i < start or i >= start + width) and (cell.text.strip() or cell.issue)
    )
    issue = next(((cell.issue, i) for i, cell in enumerate(inside) if cell.issue), (None, None))
    return texts, outside, issue[0], issue[1]


def header_names(cells: list[_Cell], layout: SheetLayout) -> list[str]:
    width = layout.last_column - layout.first_column + 1
    texts, _, _, _ = _span(cells, layout, width)
    return [text.strip() or f"coluna_{i + 1}" for i, text in enumerate(texts)]


def parse_xlsx_sample(path: Path, options: ParseOptions, max_rows: int) -> XlsxSample:
    books = _Workbooks(path, options.sheet)
    try:
        layout = detect_layout(books.rows(1), options.header_row)
        if layout.last_column == 0:
            raise FileRejected(
                f"Nenhum dado encontrado a partir da linha {options.header_row or 1} da aba '{books.sheet}'.",
                "no_rows",
            )
        width = layout.last_column - layout.first_column + 1
        rows = books.rows(layout.header_row)
        header: list[str]
        if options.has_header:
            _, header_cells = next(rows)
            header = header_names(header_cells, layout)
        else:
            header = [f"coluna_{i + 1}" for i in range(width)]
            rows = books.rows(layout.header_row)
        body: list[list[str]] = []
        ragged = empty = issues = 0
        pending_empty = 0
        truncated = False
        for _, cells in rows:
            texts, outside, issue, _ = _span(cells, layout, width)
            if not any(text.strip() for text in texts) and not outside and issue is None:
                pending_empty += 1
                continue
            empty += pending_empty  # vazias entre registros contam; as do fim da aba não
            pending_empty = 0
            if len(body) >= max_rows:
                truncated = True
                break
            ragged += 1 if outside else 0
            issues += 1 if issue else 0
            body.append(texts)
        sheets = books.sheets
        sheet = books.sheet
        # Dimensão declarada ao abrir (antes de `reset_dimensions`); sem ela, conta as linhas.
        found = next((s["declared_rows"] for s in sheets if s["name"] == sheet), None)
        declared = found if isinstance(found, int) else None
        if truncated and declared is None:
            declared = _count_xml_rows(books.values[sheet])
    finally:
        books.close()
    last_row = (declared if truncated else None) or layout.header_row + len(body) + empty
    estimated = max(last_row - layout.header_row, 0) if options.has_header else last_row
    table = SampleTable(
        header=header,
        rows=body,
        column_count=width,
        ragged_rows=ragged,
        empty_rows=empty,
        truncated=truncated,
        complete=not truncated,
    )
    data_range = (
        f"{column_letter(layout.first_column)}{layout.header_row}:"
        f"{column_letter(layout.last_column)}{max(last_row, layout.header_row)}"
    )
    return XlsxSample(
        table=table,
        sheet=sheet,
        sheets=sheets,
        layout=layout,
        data_range=data_range,
        cell_issues=issues,
        estimated_rows=estimated if truncated else None,
    )


@dataclass
class XlsxReadStats:
    trailing_empty_rows: int = 0


def read_xlsx_batches(
    path: Path,
    options: ParseOptions,
    expected_header: list[str] | None,
    column_count: int,
    first_column: int,
    batch_rows: int,
    stats: XlsxReadStats | None = None,
) -> Iterator[RawBatch]:
    books = _Workbooks(path, options.sheet)
    # A importação congela a linha detectada na pré-visualização; 1 só por segurança.
    header_row = options.header_row or 1
    layout = SheetLayout(
        header_row=header_row,
        first_column=first_column,
        last_column=first_column + column_count - 1,
    )
    try:
        rows = books.rows(header_row)
        if options.has_header:
            try:
                _, header_cells = next(rows)
            except StopIteration:
                return
            names = header_names(header_cells, layout)
            if expected_header is not None and names != expected_header:
                raise HeaderMismatch("O cabeçalho da aba não corresponde às colunas configuradas.")

        values: list[list[str]] = []
        record_rows: list[int] = []
        lines: list[int] = []
        structs: list[str | None] = []
        reasons: list[str | None] = []
        cell_columns: list[int | None] = []
        extra: dict[int, int] = {}
        record = 0
        pending_empty: list[int] = []

        def append(
            line: int, texts: list[str], struct: str | None, reason: str | None, col: int | None
        ) -> None:
            nonlocal record
            record += 1
            values.append(texts)
            record_rows.append(record)
            lines.append(line)
            structs.append(struct)
            reasons.append(reason)
            cell_columns.append(col)

        def flush() -> RawBatch:
            frame = build_raw_frame(
                column_count, values, record_rows, lines, structs, reasons, cell_columns
            )
            return RawBatch(frame=frame, bytes_read=None, extra_fields=dict(extra))

        for line, cells in rows:
            texts, outside, issue, issue_col = _span(cells, layout, column_count)
            if not any(text.strip() for text in texts) and not outside and issue is None:
                pending_empty.append(line)
                continue
            # Linhas vazias entre registros são registros rejeitados; as do fim da aba, não.
            for empty_line in pending_empty:
                append(empty_line, [""] * column_count, StructuralError.EMPTY_ROW, None, None)
            pending_empty = []
            struct = None
            if outside:
                struct = StructuralError.TOO_MANY_FIELDS
                extra[record + 1] = column_count + outside
            append(line, texts, struct, issue, issue_col)
            if len(record_rows) >= batch_rows:
                yield flush()
                values, record_rows, lines, structs = [], [], [], []
                reasons, cell_columns, extra = [], [], {}
        if record_rows or record == 0:
            yield flush()
        if stats is not None:
            stats.trailing_empty_rows = len(pending_empty)
    finally:
        books.close()
