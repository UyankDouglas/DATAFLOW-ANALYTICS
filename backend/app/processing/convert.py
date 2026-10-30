"""Conversão vetorizada de tipos com Polars e separação entre registros válidos e rejeitados.

Regras (versão em types.RULES_VERSION):
- Valores presentes em `null_values` viram nulo em todas as colunas.
- Colunas de texto são preservadas exatamente como recebidas (sem trim).
- Demais tipos ignoram espaços nas bordas antes de converter.
- Um valor não nulo que não converte para o tipo configurado rejeita o registro inteiro,
  com motivo, coluna e linha rastreáveis. Nada é descartado silenciosamente.
- Decimais usam Decimal(38, escala) — nunca ponto flutuante. Valores com mais casas que a
  escala configurada são rejeitados em vez de arredondados.
"""

from collections import Counter
from dataclasses import dataclass, field

import polars as pl

from app.processing.reader import StructuralError, raw_column
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

META_COLUMNS = ("__df_row", "__df_line", "__df_reason", "__df_column", "__df_detail")

_BOOL_MAP = {**dict.fromkeys(BOOLEAN_TRUE, True), **dict.fromkeys(BOOLEAN_FALSE, False)}

TYPE_LABELS = {
    DataType.TEXT: "texto",
    DataType.INTEGER: "inteiro",
    DataType.DECIMAL: "decimal",
    DataType.DATE: "data",
    DataType.DATETIME: "data e hora",
    DataType.BOOLEAN: "booleano",
}


def polars_dtype(column: ColumnConfig) -> pl.DataType:
    match column.data_type:
        case DataType.TEXT:
            return pl.String()
        case DataType.INTEGER:
            return pl.Int64()
        case DataType.DECIMAL:
            return pl.Decimal(DECIMAL_PRECISION, column.scale or 0)
        case DataType.DATE:
            return pl.Date()
        case DataType.DATETIME:
            return pl.Datetime("us")
        case DataType.BOOLEAN:
            return pl.Boolean()


def _numeric_text(expr: pl.Expr, options: ParseOptions) -> pl.Expr:
    expr = expr.str.strip_chars()
    if options.thousands_separator:
        expr = expr.str.replace_all(options.thousands_separator, "", literal=True)
    if options.decimal_separator == ",":
        expr = expr.str.replace_all(",", ".", literal=True)
    return expr


def _convert(
    column: ColumnConfig, source: pl.Expr, options: ParseOptions
) -> tuple[pl.Expr, pl.Expr | None]:
    """Retorna (valor convertido, flag de escala excedida opcional)."""
    match column.data_type:
        case DataType.TEXT:
            return source, None
        case DataType.INTEGER:
            text = _numeric_text(source, options)
            valid = text.str.contains(r"^[+-]?\d+$")
            return pl.when(valid).then(text).otherwise(None).cast(pl.Int64, strict=False), None
        case DataType.DECIMAL:
            text = _numeric_text(source, options)
            valid = text.str.contains(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
            fraction = text.str.split(".").list.get(1, null_on_oob=True).str.len_chars()
            too_many = valid & fraction.is_not_null() & (fraction > (column.scale or 0))
            value = (
                pl.when(valid & ~too_many)
                .then(text)
                .otherwise(None)
                .cast(polars_dtype(column), strict=False)
            )
            return value, too_many
        case DataType.DATE:
            return source.str.strip_chars().str.to_date(column.format, strict=False), None
        case DataType.DATETIME:
            return (
                source.str.strip_chars().str.to_datetime(
                    column.format, strict=False, time_unit="us"
                ),
                None,
            )
        case DataType.BOOLEAN:
            lowered = source.str.strip_chars().str.to_lowercase()
            return lowered.replace_strict(_BOOL_MAP, default=None, return_dtype=pl.Boolean), None


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
    failures: list[pl.Expr] = []
    scale_flags: list[pl.Expr] = []

    for column in columns:
        src = pl.col(raw_column(column.position))
        if column.data_type == DataType.TEXT:
            is_null = src.is_in(nulls)
        else:
            is_null = src.is_in(nulls) | src.str.strip_chars().is_in(stripped_nulls)
        original = pl.when(is_null).then(None).otherwise(src)
        value, too_many = _convert(column, original, options)
        originals.append(original.alias(f"o{column.position}"))
        converted.append(value.alias(f"v{column.position}"))
        failures.append((original.is_not_null() & value.is_null()).alias(f"f{column.position}"))
        scale_flags.append(
            (too_many if too_many is not None else pl.lit(False)).alias(f"s{column.position}")
        )

    frame = raw.with_columns(*originals).with_columns(*converted, *failures, *scale_flags)
    struct_ok = pl.col("__df_struct").is_null()
    failure_candidates: list[pl.Expr] = [
        pl.when(pl.col(f"f{c.position}")).then(pl.lit(i)) for i, c in enumerate(columns)
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
            failed = int(typed[f"f{column.position}"].sum())
            if failed:
                result.column_failures[column.name] += failed
    return result


def _build_rejections(
    frame: pl.DataFrame, columns: list[ColumnConfig], extra_fields: dict[int, int]
) -> pl.DataFrame:
    names = [c.name for c in columns]
    schema: dict[str, pl.DataType] = {
        "__df_row": pl.Int64(),
        "__df_line": pl.Int64(),
        "__df_reason": pl.String(),
        "__df_column": pl.String(),
        "__df_detail": pl.String(),
        **{name: pl.String() for name in names},
    }
    if frame.height == 0:
        return pl.DataFrame(schema=schema)

    index_to_name = {i: c.name for i, c in enumerate(columns)}
    index_to_detail = {}
    index_to_scale_detail = {}
    for i, c in enumerate(columns):
        label = TYPE_LABELS[c.data_type]
        if c.format:
            label += f" (formato {DATE_FORMATS.get(c.format) or DATETIME_FORMATS.get(c.format, c.format)})"
        index_to_detail[i] = f"Valor não corresponde ao tipo {label}."
        index_to_scale_detail[i] = (
            f"Valor possui mais de {c.scale} casas decimais; não foi arredondado."
            if c.data_type == DataType.DECIMAL
            else index_to_detail[i]
        )

    idx = pl.col("__df_fail_idx")
    scale_candidates: list[pl.Expr] = [
        pl.when(idx == i).then(pl.col(f"s{c.position}")) for i, c in enumerate(columns)
    ]
    scale_hit = pl.coalesce(scale_candidates or [pl.lit(False)]).fill_null(False)
    struct_detail = {
        StructuralError.EMPTY_ROW: "Registro sem nenhum valor preenchido.",
        StructuralError.TOO_FEW_FIELDS: f"Registro com menos campos que as {len(columns)} colunas.",
        StructuralError.TOO_MANY_FIELDS: f"Registro com mais campos que as {len(columns)} colunas.",
        StructuralError.MALFORMED: "Aspas malformadas ou campo acima do limite permitido.",
    }
    out = frame.select(
        pl.col("__df_row"),
        pl.col("__df_line"),
        pl.when(pl.col("__df_struct").is_not_null())
        .then(pl.col("__df_struct"))
        .when(scale_hit)
        .then(pl.lit(SCALE_ERROR))
        .otherwise(pl.lit(TYPE_ERROR))
        .alias("__df_reason"),
        pl.when(pl.col("__df_struct").is_null())
        .then(idx.replace_strict(index_to_name, default=None, return_dtype=pl.String))
        .alias("__df_column"),
        pl.when(pl.col("__df_struct").is_not_null())
        .then(
            pl.col("__df_struct").replace_strict(
                struct_detail, default=None, return_dtype=pl.String
            )
        )
        .when(scale_hit)
        .then(idx.replace_strict(index_to_scale_detail, default=None, return_dtype=pl.String))
        .otherwise(idx.replace_strict(index_to_detail, default=None, return_dtype=pl.String))
        .alias("__df_detail"),
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
