"""Leitura de CSV em lotes, em streaming, com validação estrutural por registro.

O tokenizador `csv` da biblioteca padrão é usado porque permite detectar, registro a
registro, linhas com campos a mais/a menos, linhas vazias e aspas malformadas — situações
que leitores colunares preenchem silenciosamente com nulos. A conversão de tipos de cada
lote é feita de forma vetorizada com Polars (ver convert.py).
"""

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import polars as pl

from app.processing.types import ParseOptions


class StructuralError:
    EMPTY_ROW = "linha_vazia"
    TOO_FEW_FIELDS = "campos_a_menos"
    TOO_MANY_FIELDS = "campos_a_mais"
    MALFORMED = "csv_malformado"


class EncodingMismatch(Exception):
    def __init__(self, line: int) -> None:
        self.line = line
        super().__init__(f"bytes inválidos para o encoding próximo à linha {line}")


class HeaderMismatch(Exception):
    pass


class _CountingReader(io.RawIOBase):
    """Conta bytes efetivamente lidos do arquivo (base do progresso real)."""

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        self.bytes_read = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        data = self._raw.read(len(buffer))
        n = len(data)
        buffer[:n] = data
        self.bytes_read += n
        return n


@dataclass
class RawBatch:
    frame: pl.DataFrame  # colunas c0..cN (texto), __df_row, __df_line, __df_struct
    bytes_read: int
    extra_fields: dict[int, int]  # registro -> quantidade de campos encontrada


def raw_column(position: int) -> str:
    return f"c{position}"


def read_batches(
    path: Path,
    options: ParseOptions,
    expected_header: list[str] | None,
    column_count: int,
    batch_rows: int,
    max_field_bytes: int,
) -> Iterator[RawBatch]:
    csv.field_size_limit(max_field_bytes)
    encoding = "utf-8-sig" if options.encoding == "utf-8" else options.encoding
    with path.open("rb") as handle:
        counter = _CountingReader(handle)
        buffered = io.BufferedReader(counter, buffer_size=1024 * 1024)
        text = io.TextIOWrapper(buffered, encoding=encoding, errors="strict", newline="")
        reader = csv.reader(text, delimiter=options.delimiter, quotechar='"', strict=True)

        if options.has_header:
            try:
                header = next(reader)
            except StopIteration:
                return
            except UnicodeDecodeError as exc:
                raise EncodingMismatch(1) from exc
            names = [value.strip() for value in header]
            if len(names) != column_count or (
                expected_header is not None
                and [n or f"coluna_{i + 1}" for i, n in enumerate(names)] != expected_header
            ):
                raise HeaderMismatch(
                    "O cabeçalho do arquivo não corresponde às colunas configuradas."
                )

        schema: dict[str, pl.DataType | type[pl.DataType]] = {
            raw_column(i): pl.String for i in range(column_count)
        }
        schema.update({"__df_row": pl.Int64, "__df_line": pl.Int64, "__df_struct": pl.String})
        padding = [""] * column_count
        empty_row = StructuralError.EMPTY_ROW
        too_few = StructuralError.TOO_FEW_FIELDS
        too_many = StructuralError.TOO_MANY_FIELDS

        def flush(
            values: list[list[str]],
            rows: list[int],
            lines: list[int],
            structs: list[str | None],
            extra: dict[int, int],
        ) -> RawBatch:
            # Transposição em C (zip) em vez de append por célula: o laço Python fica só por linha.
            transposed = list(zip(*values, strict=True)) if values else [()] * column_count
            data: dict[str, object] = {raw_column(i): col for i, col in enumerate(transposed)}
            data.update({"__df_row": rows, "__df_line": lines, "__df_struct": structs})
            frame = pl.DataFrame(data, schema=schema)
            return RawBatch(frame=frame, bytes_read=counter.bytes_read, extra_fields=extra)

        values: list[list[str]] = []
        rows: list[int] = []
        lines: list[int] = []
        structs: list[str | None] = []
        extra: dict[int, int] = {}
        record = 0
        last_line = reader.line_num

        while True:
            struct: str | None = None
            try:
                row = next(reader)
            except StopIteration:
                break
            except UnicodeDecodeError as exc:
                raise EncodingMismatch(reader.line_num + 1) from exc
            except csv.Error:
                row, struct = [], StructuralError.MALFORMED
            record += 1
            start_line = last_line + 1
            last_line = reader.line_num
            size = len(row)
            if size == column_count and struct is None:
                if not "".join(row).strip():
                    struct = empty_row
                values.append(row)
            else:
                if struct is None:
                    if not "".join(row).strip():
                        struct = empty_row
                    elif size < column_count:
                        struct = too_few
                    else:
                        struct = too_many
                        extra[record] = size
                values.append((row + padding)[:column_count])
            rows.append(record)
            lines.append(start_line)
            structs.append(struct)

            if len(rows) >= batch_rows:
                yield flush(values, rows, lines, structs, extra)
                values, rows, lines, structs, extra = [], [], [], [], {}

        if rows or record == 0:
            yield flush(values, rows, lines, structs, extra)
