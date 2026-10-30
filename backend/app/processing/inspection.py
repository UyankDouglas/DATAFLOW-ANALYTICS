"""Inspeção de arquivos no recebimento e leitura de amostras para pré-visualização.

Tudo aqui opera em streaming ou sobre uma amostra limitada; nunca sobre o arquivo inteiro
em memória.
"""

import codecs
import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any

from app.processing.types import DEFAULT_NULL_VALUES, ParseOptions

HEAD_BYTES = 64 * 1024

# Assinaturas de formatos binários que nunca são CSV.
_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "arquivo compactado (ZIP/XLSX)"),
    (b"\xd0\xcf\x11\xe0", "documento do Office legado (XLS/DOC)"),
    (b"%PDF", "PDF"),
    (b"MZ", "executável"),
    (b"\x7fELF", "executável"),
    (b"\x89PNG", "imagem PNG"),
    (b"\xff\xd8\xff", "imagem JPEG"),
    (b"GIF8", "imagem GIF"),
    (b"\x1f\x8b", "arquivo GZIP"),
    (b"Rar!", "arquivo RAR"),
    (b"7z\xbc\xaf", "arquivo 7z"),
)

_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_CANDIDATE_DELIMITERS = (";", ",", "\t", "|")


class FileRejected(Exception):
    """Arquivo recusado no recebimento. A mensagem é segura para o usuário."""

    def __init__(self, message: str, code: str = "invalid_file") -> None:
        self.code = code
        super().__init__(message)


@dataclass
class StreamInspector:
    """Acumula hash, tamanho, contagem de linhas e validade UTF-8 enquanto o upload chega."""

    size: int = 0
    newlines: int = 0
    utf8_valid: bool = True
    head: bytes = b""
    last_byte: bytes = b""
    _sha: Any = field(default_factory=hashlib.sha256)
    _decoder: Any = field(default_factory=lambda: codecs.getincrementaldecoder("utf-8")())

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        if len(self.head) < HEAD_BYTES:
            self.head += chunk[: HEAD_BYTES - len(self.head)]
            self._check_head_early()
        self.size += len(chunk)
        self.newlines += chunk.count(b"\n")
        self.last_byte = chunk[-1:]
        self._sha.update(chunk)
        if self.utf8_valid:
            try:
                self._decoder.decode(chunk)
            except UnicodeDecodeError:
                self.utf8_valid = False

    def _check_head_early(self) -> None:
        for signature, label in _MAGIC_SIGNATURES:
            if self.head.startswith(signature):
                raise FileRejected(
                    f"O conteúdo do arquivo é {label}, não um CSV de texto.", "content_mismatch"
                )
        if self.head.startswith(_UTF16_BOMS):
            raise FileRejected(
                "O arquivo está em UTF-16. Salve-o como CSV UTF-8 e envie novamente.",
                "unsupported_encoding",
            )

    def finish(self) -> dict[str, Any]:
        if self.size == 0:
            raise FileRejected("O arquivo está vazio.", "empty_file")
        if self.utf8_valid:
            try:
                self._decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                self.utf8_valid = False
        if b"\x00" in self.head:
            raise FileRejected(
                "O arquivo contém bytes nulos e parece ser binário, não um CSV de texto.",
                "content_mismatch",
            )
        has_bom = self.head.startswith(codecs.BOM_UTF8)
        lines = self.newlines + (0 if self.last_byte == b"\n" else 1)
        encoding = "utf-8" if self.utf8_valid else None
        sample_text = decode_sample(
            self.head, encoding or "windows-1252", truncated=True, lenient=True
        )
        delimiter = sniff_delimiter(sample_text)
        number_format = suggest_number_format(sample_text, delimiter)
        return {
            "sha256": self._sha.hexdigest(),
            "size_bytes": self.size,
            "utf8_valid": self.utf8_valid,
            "has_bom": has_bom,
            "encoding": encoding,
            "suggested_encoding": encoding or "windows-1252",
            "delimiter": delimiter,
            "decimal_separator": number_format[0],
            "thousands_separator": number_format[1],
            # Quebras de linha, não registros: campos entre aspas podem conter quebras.
            "line_count": lines,
        }


def decode_sample(data: bytes, encoding: str, *, truncated: bool, lenient: bool = False) -> str:
    """Decodifica uma amostra. Se truncada, descarta a última linha possivelmente incompleta.

    A decodificação é estrita (mesma regra do worker), exceto quando `lenient` é usado apenas
    para heurísticas de detecção.
    """
    if data.startswith(codecs.BOM_UTF8):
        data = data[len(codecs.BOM_UTF8) :]
    if truncated:
        cut = data.rfind(b"\n")
        if cut > 0:
            data = data[: cut + 1]
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace" if lenient else "strict")
    # final=False tolera um caractere multibyte cortado no fim de uma amostra truncada.
    return str(decoder.decode(data, final=not truncated))


def sniff_delimiter(sample: str) -> str:
    """Escolhe o delimitador que produz a contagem de campos mais consistente."""
    lines = [line for line in sample.splitlines()[:60] if line.strip()]
    if not lines:
        return ","
    best, best_score = ",", 0.0
    text = "\n".join(lines)
    for delimiter in _CANDIDATE_DELIMITERS:
        try:
            counts = [len(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
        except csv.Error:
            continue
        if not counts:
            continue
        modal = max(set(counts), key=counts.count)
        if modal <= 1:
            continue
        score = counts.count(modal) / len(counts) + min(modal, 50) / 1000
        if score > best_score:
            best, best_score = delimiter, score
    return best


_BR_NUMBER = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$|^-?\d+,\d+$")
_US_NUMBER = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$|^-?\d+\.\d+$")


def suggest_number_format(sample: str, delimiter: str) -> tuple[str, str]:
    """Sugere separadores decimal/milhar a partir de valores numéricos da amostra."""
    br = us = 0
    try:
        for row in csv.reader(io.StringIO(sample), delimiter=delimiter):
            for value in row[:200]:
                value = value.strip()
                if _BR_NUMBER.match(value):
                    br += 1
                elif _US_NUMBER.match(value):
                    us += 1
    except csv.Error:
        return ".", ""
    if br > us:
        return ",", "."
    return ".", ""


@dataclass
class SampleTable:
    header: list[str]
    rows: list[list[str]]
    column_count: int
    ragged_rows: int
    empty_rows: int
    truncated: bool
    # True quando todos os registros do arquivo couberam na amostra (contagem exata).
    complete: bool


def parse_sample(
    data: bytes, options: ParseOptions, *, truncated: bool, max_rows: int
) -> SampleTable:
    """Interpreta a amostra com as opções informadas (mesmas regras do worker)."""
    try:
        text = decode_sample(data, options.encoding, truncated=truncated)
    except UnicodeDecodeError as exc:
        raise FileRejected(
            "A amostra não é válida no encoding selecionado. Escolha outro encoding.",
            "encoding_mismatch",
        ) from exc
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=options.delimiter, strict=False)
    rows: list[list[str]] = []
    empty = 0
    stopped_early = False
    try:
        for row in reader:
            if not row or all(not value.strip() for value in row):
                empty += 1
                continue
            rows.append(row)
            if len(rows) > max_rows + (1 if options.has_header else 0):
                stopped_early = True
                break
    except csv.Error as exc:
        raise FileRejected(f"Não foi possível interpretar o CSV: {exc}", "malformed_csv") from exc
    if not rows:
        raise FileRejected("Nenhum registro encontrado com as opções selecionadas.", "no_rows")

    if options.has_header:
        raw_header, body = rows[0], rows[1:]
    else:
        raw_header, body = [], rows
    column_count = len(raw_header) if options.has_header else max(len(r) for r in body[:50])
    if options.has_header:
        header = [value.strip() or f"coluna_{index + 1}" for index, value in enumerate(raw_header)]
    else:
        header = [f"coluna_{index + 1}" for index in range(column_count)]
    ragged = sum(1 for row in body if len(row) != column_count)
    return SampleTable(
        header=header,
        rows=body[:max_rows],
        column_count=column_count,
        ragged_rows=ragged,
        empty_rows=empty,
        truncated=truncated,
        complete=not truncated and not stopped_early,
    )


def default_null_values() -> list[str]:
    return list(DEFAULT_NULL_VALUES)
