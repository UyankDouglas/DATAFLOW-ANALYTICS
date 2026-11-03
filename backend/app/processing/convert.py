"""Conversão vetorizada de tipos com Polars e separação entre registros válidos e rejeitados.

Regras (versão em types.RULES_VERSION):
- Valores presentes em `null_values` viram nulo em todas as colunas.
- Colunas de texto são preservadas exatamente como recebidas (sem trim).
- Demais tipos ignoram espaços nas bordas antes de converter.
- Um valor não nulo que não converte para o tipo configurado rejeita o registro inteiro,
  com motivo, coluna e linha rastreáveis. Nada é descartado silenciosamente.
- Decimais usam Decimal(38, escala) — nunca ponto flutuante. Valores com mais casas que a
  escala configurada são rejeitados em vez de arredondados.
- Nulos recebem o `fill_value` da coluna, quando configurado; depois disso, coluna
  obrigatória sem valor rejeita o registro (`campo_obrigatorio`).
- Problemas de célula do XLSX (fórmula sem valor salvo, erro do Excel) rejeitam o registro.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from app.processing.reader import CellIssue, StructuralError, raw_column
from app.processing.types import (
    BOOLEAN_FALSE,
    BOOLEAN_TRUE,
    DATE_FORMATS,
    DATETIME_FORMATS,
    DECIMAL_PRECISION,
    ColumnConfig,
    DataType,
    ParseOptions,
)

TYPE_ERROR = "tipo_invalido"
SCALE_ERROR = "casas_decimais_excedidas"
REQUIRED_ERROR = "campo_obrigatorio"

CATEGORY_REJECTED = "rejeitado"
CATEGORY_FILTERED = "filtrado"
CATEGORY_DUPLICATE = "duplicado"

# Ordem fixa: as cinco primeiras existem desde a Fase 1 (Parquets antigos só têm essas).
META_COLUMNS = (
    "__df_row",
    "__df_line",
    "__df_reason",
    "__df_column",
    "__df_detail",
    "__df_category",
    "__df_rule",
    "__df_duplicate_of",
)
META_SCHEMA: dict[str, pl.DataType] = {
    "__df_row": pl.Int64(),
    "__df_line": pl.Int64(),
    "__df_reason": pl.String(),
    "__df_column": pl.String(),
    "__df_detail": pl.String(),
    "__df_category": pl.String(),
    "__df_rule": pl.Int32(),
    "__df_duplicate_of": pl.Int64(),
}

_BOOL_MAP = {**dict.fromkeys(BOOLEAN_TRUE, True), **dict.fromkeys(BOOLEAN_FALSE, False)}

TYPE_LABELS = {
    DataType.TEXT: "texto",
    DataType.INTEGER: "inteiro",
    DataType.DECIMAL: "decimal",
    DataType.DATE: "data",
    DataType.DATETIME: "data e hora",
    DataType.BOOLEAN: "booleano",
}

CELL_DETAIL = {
    CellIssue.FORMULA_WITHOUT_VALUE: "Fórmula sem valor calculado salvo no arquivo; o DataFlow não calcula fórmulas.",
    CellIssue.CELL_ERROR: "A célula contém um erro do Excel (ex.: #DIV/0!, #N/D).",
}

# Formatos canônicos para valores digitados na configuração (preenchimento, filtros).
CANONICAL_FORMATS = {DataType.DATE: "%Y-%m-%d", DataType.DATETIME: "%Y-%m-%d %H:%M:%S"}
CANONICAL_OPTIONS = ParseOptions(decimal_separator=".", thousands_separator="")


def polars_dtype(data_type: DataType, scale: int | None) -> pl.DataType:
    match data_type:
        case DataType.TEXT:
            return pl.String()
        case DataType.INTEGER:
            return pl.Int64()
        case DataType.DECIMAL:
            return pl.Decimal(DECIMAL_PRECISION, scale or 0)
        case DataType.DATE:
            return pl.Date()
        case DataType.DATETIME:
            return pl.Datetime("us")
        case DataType.BOOLEAN:
            return pl.Boolean()


def format_label(fmt: str | None) -> str:
    if not fmt:
        return ""
    return DATE_FORMATS.get(fmt) or DATETIME_FORMATS.get(fmt, fmt)


def type_label(data_type: DataType, fmt: str | None = None) -> str:
    label = TYPE_LABELS[data_type]
    return f"{label} (formato {format_label(fmt)})" if fmt else label


def numeric_text(expr: pl.Expr, decimal_separator: str, thousands_separator: str) -> pl.Expr:
    expr = expr.str.strip_chars()
    if thousands_separator:
        expr = expr.str.replace_all(thousands_separator, "", literal=True)
    if decimal_separator == ",":
        expr = expr.str.replace_all(",", ".", literal=True)
    return expr


def text_to_type(
    source: pl.Expr,
    data_type: DataType,
    *,
    fmt: str | None,
    scale: int | None,
    decimal_separator: str = ".",
    thousands_separator: str = "",
) -> tuple[pl.Expr, pl.Expr | None]:
    """Converte texto no tipo pedido. Retorna (valor, flag de escala excedida)."""
    match data_type:
        case DataType.TEXT:
            return source, None
        case DataType.INTEGER:
            text = numeric_text(source, decimal_separator, thousands_separator)
            valid = text.str.contains(r"^[+-]?\d+$")
            return pl.when(valid).then(text).otherwise(None).cast(pl.Int64, strict=False), None
        case DataType.DECIMAL:
            text = numeric_text(source, decimal_separator, thousands_separator)
            valid = text.str.contains(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
            fraction = text.str.split(".").list.get(1, null_on_oob=True).str.len_chars()
            too_many = valid & fraction.is_not_null() & (fraction > (scale or 0))
            value = (
                pl.when(valid & ~too_many)
                .then(text)
                .otherwise(None)
                .cast(polars_dtype(DataType.DECIMAL, scale), strict=False)
            )
            return value, too_many
        case DataType.DATE:
            return source.str.strip_chars().str.to_date(fmt, strict=False), None
        case DataType.DATETIME:
            return (
                source.str.strip_chars().str.to_datetime(fmt, strict=False, time_unit="us"),
                None,
            )
        case DataType.BOOLEAN:
            lowered = source.str.strip_chars().str.to_lowercase()
            return lowered.replace_strict(_BOOL_MAP, default=None, return_dtype=pl.Boolean), None


def canonical_value(data_type: DataType, scale: int | None, text: str) -> Any:
    """Converte um valor digitado na configuração (formato canônico) ou lança ValueError."""
    expr, too_many = text_to_type(
        pl.lit(text), data_type, fmt=CANONICAL_FORMATS.get(data_type), scale=scale
    )
    frame = pl.select(
        expr.alias("v"), (too_many if too_many is not None else pl.lit(False)).alias("s")
    )
    value = frame["v"][0]
    if value is None or bool(frame["s"][0]):
        hint = {
            DataType.DATE: "use aaaa-mm-dd",
            DataType.DATETIME: "use aaaa-mm-dd hh:mm:ss",
            DataType.DECIMAL: f"use ponto como separador decimal e até {scale} casas",
            DataType.INTEGER: "use apenas dígitos",
            DataType.BOOLEAN: "use true ou false",
        }.get(data_type, "")
        raise ValueError(f"'{text}' não é um valor {TYPE_LABELS[data_type]} válido ({hint})")
    return value


@dataclass
class BatchResult:
    valid: pl.DataFrame
    rejected: pl.DataFrame
    reasons: Counter[str] = field(default_factory=Counter)
    column_failures: Counter[str] = field(default_factory=Counter)


def convert_batch(
    raw: pl.DataFrame,
    columns: list[ColumnConfig],
    options: ParseOptions,
    extra_fields: dict[int, int],
) -> BatchResult:
    nulls = list(options.null_values)
    stripped_nulls = [n.strip() for n in nulls]
    originals: list[pl.Expr] = []
    converted: list[pl.Expr] = []
    codes: list[pl.Expr] = []

    # Três etapas, cada uma sobre colunas já calculadas (o, depois v/s, depois e): a conversão
    # de cada coluna roda uma única vez, sem depender da eliminação de subexpressões do Polars.
    for column in columns:
        position = column.position
        src = pl.col(raw_column(position))
        if column.data_type == DataType.TEXT:
            is_null = src.is_in(nulls)
        else:
            is_null = src.is_in(nulls) | src.str.strip_chars().is_in(stripped_nulls)
        originals.append(pl.when(is_null).then(None).otherwise(src).alias(f"o{position}"))

        original = pl.col(f"o{position}")
        value, too_many = text_to_type(
            original,
            column.data_type,
            fmt=column.format,
            scale=column.scale,
            decimal_separator=options.decimal_separator,
            thousands_separator=options.thousands_separator,
        )
        if column.fill_value is not None:
            fill = canonical_value(column.data_type, column.scale, column.fill_value)
            dtype = polars_dtype(column.data_type, column.scale)
            value = pl.when(original.is_null()).then(pl.lit(fill, dtype=dtype)).otherwise(value)
        converted.append(value.alias(f"v{position}"))
        converted.append(
            (too_many if too_many is not None else pl.lit(False)).alias(f"s{position}")
        )

        # Com valor para vazios, só valores presentes chegam aqui: falha de tipo é presente → nulo.
        converted_value = pl.col(f"v{position}")
        type_failed = original.is_not_null() & converted_value.is_null()
        code = (
            pl.when(type_failed & pl.col(f"s{position}"))
            .then(pl.lit(SCALE_ERROR))
            .when(type_failed)
            .then(pl.lit(TYPE_ERROR))
        )
        if column.required:
            code = code.when(converted_value.is_null()).then(pl.lit(REQUIRED_ERROR))
        codes.append(code.otherwise(None).alias(f"e{position}"))

    frame = raw.with_columns(*originals).with_columns(*converted).with_columns(*codes)
    struct_ok = pl.col("__df_struct").is_null() & pl.col("__df_cell_reason").is_null()
    failure_candidates: list[pl.Expr] = [
        pl.when(pl.col(f"e{c.position}").is_not_null()).then(pl.lit(i))
        for i, c in enumerate(columns)
    ]
    first_failure = pl.coalesce(failure_candidates or [pl.lit(None)]).cast(pl.Int32)
    frame = frame.with_columns(first_failure.alias("__df_fail_idx"))
    is_valid = struct_ok & pl.col("__df_fail_idx").is_null()

    valid = frame.filter(is_valid).select(
        pl.col("__df_row"),
        *[pl.col(f"v{c.position}").alias(c.name) for c in columns],
    )

    rejected_raw = frame.filter(~is_valid)
    result = BatchResult(
        valid=valid, rejected=_build_rejections(rejected_raw, columns, extra_fields)
    )
    if rejected_raw.height:
        result.reasons.update(result.rejected["__df_reason"].to_list())
        typed = rejected_raw.filter(struct_ok)
        for column in columns:
            failed = int(typed[f"e{column.position}"].is_not_null().sum())
            if failed:
                result.column_failures[column.name] += failed
    return result


def _build_rejections(
    frame: pl.DataFrame, columns: list[ColumnConfig], extra_fields: dict[int, int]
) -> pl.DataFrame:
    names = [c.name for c in columns]
    schema: dict[str, pl.DataType] = {**META_SCHEMA, **{name: pl.String() for name in names}}
    if frame.height == 0:
        return pl.DataFrame(schema=schema)

    index_to_name = {i: c.name for i, c in enumerate(columns)}
    position_to_name = {c.position: c.name for c in columns}
    details: dict[str, dict[int, str]] = {TYPE_ERROR: {}, SCALE_ERROR: {}, REQUIRED_ERROR: {}}
    for i, c in enumerate(columns):
        details[TYPE_ERROR][i] = (
            f"Valor não corresponde ao tipo {type_label(c.data_type, c.format)}."
        )
        details[SCALE_ERROR][i] = (
            f"Valor possui mais de {c.scale} casas decimais; não foi arredondado."
        )
        details[REQUIRED_ERROR][i] = "Coluna obrigatória sem valor."

    idx = pl.col("__df_fail_idx")
    code_candidates: list[pl.Expr] = [
        pl.when(idx == i).then(pl.col(f"e{c.position}")) for i, c in enumerate(columns)
    ]
    column_code = pl.coalesce(code_candidates or [pl.lit(None, dtype=pl.String)])
    struct_detail = {
        StructuralError.EMPTY_ROW: "Registro sem nenhum valor preenchido.",
        StructuralError.TOO_FEW_FIELDS: f"Registro com menos campos que as {len(columns)} colunas.",
        StructuralError.TOO_MANY_FIELDS: f"Registro com mais campos que as {len(columns)} colunas.",
        StructuralError.MALFORMED: "Aspas malformadas ou campo acima do limite permitido.",
    }
    detail_by_code = pl.coalesce(
        pl.when(column_code == code).then(
            idx.replace_strict(details[code], default=None, return_dtype=pl.String)
        )
        for code in (TYPE_ERROR, SCALE_ERROR, REQUIRED_ERROR)
    )

    struct = pl.col("__df_struct")
    cell = pl.col("__df_cell_reason")
    out = frame.with_columns(column_code.alias("__df_code")).select(
        pl.col("__df_row"),
        pl.col("__df_line"),
        pl.when(struct.is_not_null())
        .then(struct)
        .when(cell.is_not_null())
        .then(cell)
        .otherwise(pl.col("__df_code"))
        .alias("__df_reason"),
        pl.when(struct.is_not_null())
        .then(pl.lit(None, dtype=pl.String))
        .when(cell.is_not_null())
        .then(
            pl.col("__df_cell_col").replace_strict(
                position_to_name, default=None, return_dtype=pl.String
            )
        )
        .otherwise(idx.replace_strict(index_to_name, default=None, return_dtype=pl.String))
        .alias("__df_column"),
        pl.when(struct.is_not_null())
        .then(struct.replace_strict(struct_detail, default=None, return_dtype=pl.String))
        .when(cell.is_not_null())
        .then(cell.replace_strict(CELL_DETAIL, default=None, return_dtype=pl.String))
        .otherwise(detail_by_code)
        .alias("__df_detail"),
        pl.lit(CATEGORY_REJECTED).alias("__df_category"),
        pl.lit(None, dtype=pl.Int32).alias("__df_rule"),
        pl.lit(None, dtype=pl.Int64).alias("__df_duplicate_of"),
        *[pl.col(raw_column(c.position)).alias(c.name) for c in columns],
    )
    if extra_fields:
        found = pl.col("__df_row").replace_strict(extra_fields, default=None, return_dtype=pl.Int64)
        out = out.with_columns(
            pl.when(found.is_not_null())
            .then(
                pl.col("__df_detail")
                + pl.lit(" Campos encontrados: ")
                + found.cast(pl.String)
                + pl.lit(".")
            )
            .otherwise(pl.col("__df_detail"))
            .alias("__df_detail")
        )
    return out.cast(schema)  # type: ignore[arg-type]
