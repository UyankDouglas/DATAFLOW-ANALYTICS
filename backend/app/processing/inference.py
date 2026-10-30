"""Inferência de tipos sobre a amostra. Ambiguidades são sinalizadas, nunca resolvidas em silêncio."""

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.processing.types import (
    BOOLEAN_FALSE,
    BOOLEAN_TRUE,
    DATE_FORMATS,
    DATETIME_FORMATS,
    MAX_DECIMAL_SCALE,
    DataType,
    ParseOptions,
)

_INT_RE = re.compile(r"^[+-]?\d+$")
_BOOL_TOKENS = (BOOLEAN_TRUE | BOOLEAN_FALSE) - {"0", "1"}
INT64_MAX = 2**63 - 1


@dataclass
class ColumnInference:
    position: int
    source_name: str
    inferred_type: DataType
    format: str | None = None
    scale: int | None = None
    ambiguous_formats: list[str] = field(default_factory=list)
    sample_size: int = 0
    null_count: int = 0
    distinct_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def null_ratio(self) -> float:
        return self.null_count / self.sample_size if self.sample_size else 0.0

    @property
    def is_empty(self) -> bool:
        return self.sample_size > 0 and self.null_count == self.sample_size


def normalize_number(value: str, options: ParseOptions) -> str:
    """Remove separador de milhar e troca o decimal por ponto, sem converter para float."""
    value = value.strip()
    if options.thousands_separator:
        value = value.replace(options.thousands_separator, "")
    if options.decimal_separator == ",":
        value = value.replace(",", ".")
    return value


_DECIMAL_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def _has_leading_zero(value: str) -> bool:
    """Zeros à esquerda indicam código (CEP, matrícula, SKU): preservar como texto."""
    if not _DECIMAL_RE.match(value):
        return False
    integer_part = value.lstrip("+-").split(".", 1)[0]
    return len(integer_part) > 1 and integer_part.startswith("0")


def _is_integer(value: str) -> bool:
    return bool(_INT_RE.match(value)) and abs(int(value)) <= INT64_MAX


def _decimal_scale(value: str) -> int | None:
    if not _DECIMAL_RE.match(value):
        return None
    _, _, fraction = value.partition(".")
    return len(fraction)


def _matches(values: list[str], fmt: str) -> bool:
    try:
        for value in values:
            datetime.strptime(value, fmt)
    except ValueError:
        return False
    return True


def infer_column(
    position: int, name: str, raw: list[str], options: ParseOptions
) -> ColumnInference:
    nulls = set(options.null_values)
    values = [v.strip() for v in raw if v not in nulls and v.strip() not in nulls]
    result = ColumnInference(
        position=position,
        source_name=name,
        inferred_type=DataType.TEXT,
        sample_size=len(raw),
        null_count=len(raw) - len(values),
        distinct_count=len(set(values)),
    )
    if not values:
        result.warnings.append("coluna_vazia_na_amostra")
        return result

    lowered = {v.lower() for v in values}
    if lowered <= _BOOL_TOKENS and len(lowered) <= 4:
        result.inferred_type = DataType.BOOLEAN
        return result

    numbers = [normalize_number(v, options) for v in values]
    if any(_has_leading_zero(n) for n in numbers):
        result.warnings.append("zeros_a_esquerda_preservados_como_texto")
        return result
    if all(_is_integer(n) for n in numbers):
        result.inferred_type = DataType.INTEGER
        return result

    scales = [_decimal_scale(n) for n in numbers]
    if all(s is not None for s in scales):
        result.inferred_type = DataType.DECIMAL
        result.scale = min(max(max(s for s in scales if s is not None), 2), MAX_DECIMAL_SCALE)
        return result

    for formats, data_type in (
        (DATE_FORMATS, DataType.DATE),
        (DATETIME_FORMATS, DataType.DATETIME),
    ):
        matching = [fmt for fmt in formats if _matches(values, fmt)]
        if matching:
            result.inferred_type = data_type
            # Preferência pt-BR (dia/mês) quando houver empate, mas sinalizada como ambígua.
            result.format = matching[0]
            if len(matching) > 1:
                result.ambiguous_formats = matching
                result.warnings.append("formato_de_data_ambiguo")
            return result

    return result


def infer_columns(
    header: list[str], rows: list[list[str]], options: ParseOptions
) -> list[ColumnInference]:
    inferences = []
    for position, name in enumerate(header):
        column = [row[position] if position < len(row) else "" for row in rows]
        inferences.append(infer_column(position, name, column, options))
    return inferences
