"""Motor de transformações configuráveis.

Só existem operações conhecidas, descritas por modelos Pydantic e validadas contra o esquema
das colunas antes de qualquer execução. Não há `eval`, SQL ou código enviado pelo usuário:
cada operação vira expressões Polars montadas aqui.

Toda linha retirada do resultado sai com categoria, motivo, regra (posição 1..n), coluna e
detalhe, para a reconciliação `recebidos = válidos + rejeitados + filtrados + duplicados`.

Arredondamentos de decimais seguem o padrão do Polars: meio para o par (bancário).
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from app.processing.convert import (
    CATEGORY_DUPLICATE,
    CATEGORY_FILTERED,
    CATEGORY_REJECTED,
    REQUIRED_ERROR,
    SCALE_ERROR,
    TYPE_ERROR,
    canonical_value,
    polars_dtype,
    text_to_type,
    type_label,
)
from app.processing.types import (
    DATE_FORMATS,
    DATETIME_FORMATS,
    DECIMAL_PRECISION,
    MAX_DECIMAL_SCALE,
    ColumnSpec,
    DataType,
    normalize_column_name,
    validate_column_name,
)

NULL_ERROR = "valor_nulo"
EMPTY_ROW_ERROR = "linha_vazia"
FILTER_REASON = "removido_por_filtro"
DIVISION_ERROR = "divisao_por_zero"
DUPLICATE_REASON = "registro_duplicado"

NUMERIC = (DataType.INTEGER, DataType.DECIMAL)
TEMPORAL = (DataType.DATE, DataType.DATETIME)
_CURRENCY = r"(R\$|US\$|\$|€|£)"

RULE_LABELS = {
    "trim": "Remover espaços excedentes",
    "normalize_text": "Normalizar texto",
    "change_case": "Padronizar maiúsculas/minúsculas",
    "convert_type": "Converter tipo",
    "standardize_dates": "Padronizar datas",
    "fix_numbers": "Corrigir formatos numéricos",
    "handle_nulls": "Tratar valores nulos",
    "remove_empty_rows": "Remover linhas totalmente vazias",
    "filter_rows": "Filtrar registros",
    "rename_columns": "Renomear colunas",
    "derived_column": "Criar coluna derivada",
    "deduplicate": "Remover duplicidades",
}

Separator = Literal[".", ","]
Thousands = Literal["", ".", ",", " "]


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True


class TrimRule(_Rule):
    operation: Literal["trim"]
    columns: list[str] = Field(min_length=1, max_length=200)
    collapse_internal: bool = True


class NormalizeTextRule(_Rule):
    operation: Literal["normalize_text"]
    columns: list[str] = Field(min_length=1, max_length=200)
    remove_accents: bool = True
    form: Literal["NFC", "NFKC"] = "NFKC"


class ChangeCaseRule(_Rule):
    operation: Literal["change_case"]
    columns: list[str] = Field(min_length=1, max_length=200)
    mode: Literal["upper", "lower", "title"]


class ConvertTypeRule(_Rule):
    operation: Literal["convert_type"]
    column: str
    target: DataType
    format: str | None = None
    scale: int | None = Field(default=None, ge=0, le=MAX_DECIMAL_SCALE)
    decimal_separator: Separator = "."
    thousands_separator: Thousands = ""


class StandardizeDatesRule(_Rule):
    operation: Literal["standardize_dates"]
    column: str
    target: Literal["date", "datetime"] = "date"
    formats: list[str] = Field(min_length=1, max_length=6)


class FixNumbersRule(_Rule):
    operation: Literal["fix_numbers"]
    column: str
    target: Literal["integer", "decimal"] = "decimal"
    scale: int | None = Field(default=None, ge=0, le=MAX_DECIMAL_SCALE)
    decimal_separator: Separator = ","
    thousands_separator: Thousands = "."
    strip_currency: bool = True
    parentheses_negative: bool = False


class HandleNullsRule(_Rule):
    operation: Literal["handle_nulls"]
    columns: list[str] = Field(min_length=1, max_length=200)
    strategy: Literal["fill", "reject"]
    fill_value: str | None = Field(default=None, max_length=200)


class RemoveEmptyRowsRule(_Rule):
    operation: Literal["remove_empty_rows"]


FilterOperator = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte", "between",
    "contains", "not_contains", "starts_with", "ends_with",
    "in", "not_in", "is_null", "not_null", "is_true", "is_false",
]  # fmt: skip

OPERATOR_LABELS = {
    "eq": "igual a", "ne": "diferente de", "gt": "maior que", "gte": "maior ou igual a",
    "lt": "menor que", "lte": "menor ou igual a", "between": "entre",
    "contains": "contém", "not_contains": "não contém", "starts_with": "começa com",
    "ends_with": "termina com", "in": "está em", "not_in": "não está em",
    "is_null": "é nulo", "not_null": "não é nulo", "is_true": "é verdadeiro",
    "is_false": "é falso",
}  # fmt: skip

_OPERATORS_BY_TYPE: dict[DataType, set[str]] = {
    DataType.TEXT: {"eq", "ne", "contains", "not_contains", "starts_with", "ends_with", "in", "not_in", "is_null", "not_null"},
    DataType.BOOLEAN: {"is_true", "is_false", "is_null", "not_null"},
    **{
        data_type: {"eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "not_in", "is_null", "not_null"}
        for data_type in (*NUMERIC, *TEMPORAL)
    },
}  # fmt: skip
_NO_VALUE = {"is_null", "not_null", "is_true", "is_false"}
_CASE_CHANGES: dict[str, Callable[[pl.Expr], pl.Expr]] = {
    "upper": lambda e: e.str.to_uppercase(),
    "lower": lambda e: e.str.to_lowercase(),
    "title": lambda e: e.str.to_titlecase(),
}
_LIST_VALUE = {"in", "not_in"}


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    operator: FilterOperator
    value: str | None = Field(default=None, max_length=200)
    value_to: str | None = Field(default=None, max_length=200)
    values: list[str] | None = Field(default=None, max_length=50)
    case_insensitive: bool = False


class FilterRowsRule(_Rule):
    operation: Literal["filter_rows"]
    conditions: list[Condition] = Field(min_length=1, max_length=10)
    match: Literal["all", "any"] = "all"


class RenameColumnsRule(_Rule):
    operation: Literal["rename_columns"]
    mapping: dict[str, str] = Field(min_length=1, max_length=200)

    @field_validator("mapping")
    @classmethod
    def _names(cls, mapping: dict[str, str]) -> dict[str, str]:
        return {source: validate_column_name(target) for source, target in mapping.items()}


class Operand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str | None = None
    value: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _one(self) -> "Operand":
        if (self.column is None) == (self.value is None):
            raise ValueError("informe uma coluna ou um valor fixo")
        return self


class ArithmeticExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["arithmetic"]
    operator: Literal["add", "subtract", "multiply", "divide"]
    left: Operand
    right: Operand
    scale: int = Field(default=2, ge=0, le=MAX_DECIMAL_SCALE)


class ConcatExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["concat"]
    parts: list[Operand] = Field(min_length=2, max_length=10)
    separator: str = Field(default=" ", max_length=10)


class DatePartExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["date_part"]
    column: str
    part: Literal["year", "month", "day", "quarter", "weekday", "year_month"]


class DateDiffExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["date_diff_days"]
    start: str
    end: str


Expression = Annotated[
    ArithmeticExpression | ConcatExpression | DatePartExpression | DateDiffExpression,
    Field(discriminator="kind"),
]


class DerivedColumnRule(_Rule):
    operation: Literal["derived_column"]
    name: str
    expression: Expression

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_column_name(value)


class DeduplicateRule(_Rule):
    operation: Literal["deduplicate"]
    # Vazio compara todas as colunas.
    columns: list[str] = Field(default_factory=list, max_length=200)
    keep: Literal["first", "last"] = "first"


Rule = Annotated[
    TrimRule
    | NormalizeTextRule
    | ChangeCaseRule
    | ConvertTypeRule
    | StandardizeDatesRule
    | FixNumbersRule
    | HandleNullsRule
    | RemoveEmptyRowsRule
    | FilterRowsRule
    | RenameColumnsRule
    | DerivedColumnRule
    | DeduplicateRule,
    Field(discriminator="operation"),
]
RULES_ADAPTER: TypeAdapter[list[Rule]] = TypeAdapter(list[Rule])

MAX_RULES = 50


class RuleError(ValueError):
    def __init__(self, index: int, message: str) -> None:
        self.index = index
        self.message = message
        super().__init__(f"Regra {index + 1}: {message}")


@dataclass
class PlannedRule:
    index: int  # posição original (0-based), inclusive regras desativadas
    rule: Any
    schema: list[ColumnSpec]  # esquema antes desta regra
    literals: dict[str, Any] = field(default_factory=dict)


@dataclass
class RulePlan:
    steps: list[PlannedRule]
    output: list[ColumnSpec]
    dedup: PlannedRule | None
    dedup_keys: list[str]


def _by_name(schema: list[ColumnSpec]) -> dict[str, ColumnSpec]:
    return {c.name: c for c in schema}


def _column(schema: list[ColumnSpec], name: str) -> ColumnSpec:
    found = _by_name(schema).get(name)
    if found is None:
        raise ValueError(f"a coluna '{name}' não existe neste ponto das regras")
    return found


def _check_unique(schema: list[ColumnSpec]) -> None:
    seen: set[str] = set()
    for column in schema:
        key = normalize_column_name(column.name).casefold()
        if key in seen:
            raise ValueError(f"o nome '{column.name}' ficaria duplicado")
        seen.add(key)


def _literal(spec: ColumnSpec, text: str | None) -> Any:
    if text is None:
        raise ValueError(f"informe um valor para a coluna '{spec.name}'")
    return canonical_value(spec.data_type, spec.scale, text)


def _plan_one(rule: Any, schema: list[ColumnSpec]) -> tuple[list[ColumnSpec], dict[str, Any]]:
    literals: dict[str, Any] = {}
    match rule:
        case TrimRule() | NormalizeTextRule() | ChangeCaseRule():
            for name in rule.columns:
                if _column(schema, name).data_type != DataType.TEXT:
                    raise ValueError(f"a coluna '{name}' não é de texto")
            return schema, literals
        case ConvertTypeRule():
            source = _column(schema, rule.column)
            target = rule.target
            from_text = source.data_type == DataType.TEXT
            if from_text and target == DataType.DATE and rule.format not in DATE_FORMATS:
                raise ValueError("escolha o formato da data")
            if from_text and target == DataType.DATETIME and rule.format not in DATETIME_FORMATS:
                raise ValueError("escolha o formato de data e hora")
            if target == DataType.DECIMAL and rule.scale is None:
                raise ValueError("informe as casas decimais")
            allowed = {
                DataType.TEXT: set(DataType),
                DataType.INTEGER: {DataType.INTEGER, DataType.DECIMAL, DataType.TEXT},
                DataType.DECIMAL: {DataType.INTEGER, DataType.DECIMAL, DataType.TEXT},
                DataType.DATE: {DataType.DATE, DataType.DATETIME, DataType.TEXT},
                DataType.DATETIME: {DataType.DATE, DataType.DATETIME, DataType.TEXT},
                DataType.BOOLEAN: {DataType.BOOLEAN, DataType.TEXT},
            }[source.data_type]
            if target not in allowed:
                raise ValueError(
                    f"conversão de {type_label(source.data_type)} para {type_label(target)} não é suportada"
                )
            fmt = rule.format if target in TEMPORAL and source.data_type == DataType.TEXT else None
            new = ColumnSpec(
                name=source.name,
                data_type=target,
                format=fmt or (source.format if target == source.data_type else None),
                scale=rule.scale if target == DataType.DECIMAL else None,
            )
            return [new if c.name == source.name else c for c in schema], literals
        case StandardizeDatesRule():
            source = _column(schema, rule.column)
            if source.data_type != DataType.TEXT:
                raise ValueError(f"a coluna '{rule.column}' não é de texto")
            allowed_formats = (
                DATE_FORMATS if rule.target == "date" else {**DATETIME_FORMATS, **DATE_FORMATS}
            )
            invalid = [f for f in rule.formats if f not in allowed_formats]
            if invalid:
                raise ValueError(f"formato não suportado: {', '.join(invalid)}")
            new = ColumnSpec(name=source.name, data_type=DataType(rule.target), format=None)
            return [new if c.name == source.name else c for c in schema], literals
        case FixNumbersRule():
            source = _column(schema, rule.column)
            if source.data_type != DataType.TEXT:
                raise ValueError(f"a coluna '{rule.column}' não é de texto")
            if rule.thousands_separator and rule.thousands_separator == rule.decimal_separator:
                raise ValueError("separador de milhar não pode ser igual ao decimal")
            if rule.target == "decimal" and rule.scale is None:
                raise ValueError("informe as casas decimais")
            target = DataType(rule.target)
            new = ColumnSpec(
                name=source.name,
                data_type=target,
                scale=rule.scale if target == DataType.DECIMAL else None,
            )
            return [new if c.name == source.name else c for c in schema], literals
        case HandleNullsRule():
            for name in rule.columns:
                spec = _column(schema, name)
                if rule.strategy == "fill":
                    literals[name] = _literal(spec, rule.fill_value)
            return schema, literals
        case RemoveEmptyRowsRule():
            return schema, literals
        case FilterRowsRule():
            for i, condition in enumerate(rule.conditions):
                spec = _column(schema, condition.column)
                if condition.operator not in _OPERATORS_BY_TYPE[spec.data_type]:
                    raise ValueError(
                        f"o operador '{OPERATOR_LABELS[condition.operator]}' não se aplica a {type_label(spec.data_type)}"
                    )
                if condition.operator in _NO_VALUE:
                    continue
                if condition.operator in _LIST_VALUE:
                    if not condition.values:
                        raise ValueError("informe ao menos um valor para a lista")
                    literals[f"{i}:values"] = [_literal(spec, v) for v in condition.values]
                    continue
                literals[f"{i}:value"] = _literal(spec, condition.value)
                if condition.operator == "between":
                    literals[f"{i}:value_to"] = _literal(spec, condition.value_to)
            return schema, literals
        case RenameColumnsRule():
            for old_name in rule.mapping:
                _column(schema, old_name)
            renamed = [
                c.model_copy(update={"name": rule.mapping.get(c.name, c.name)}) for c in schema
            ]
            _check_unique(renamed)
            return renamed, literals
        case DerivedColumnRule():
            spec = _derived_spec(rule, schema, literals)
            updated = [*schema, spec]
            _check_unique(updated)
            return updated, literals
        case DeduplicateRule():
            for name in rule.columns:
                _column(schema, name)
            return schema, literals
    raise ValueError("operação desconhecida")


def _operand_spec(operand: Operand, schema: list[ColumnSpec]) -> ColumnSpec | None:
    return _column(schema, operand.column) if operand.column is not None else None


def _derived_spec(
    rule: DerivedColumnRule, schema: list[ColumnSpec], literals: dict[str, Any]
) -> ColumnSpec:
    expression = rule.expression
    match expression:
        case ArithmeticExpression():
            for side, operand in (("left", expression.left), ("right", expression.right)):
                spec = _operand_spec(operand, schema)
                if spec is not None and spec.data_type not in NUMERIC:
                    raise ValueError(f"a coluna '{operand.column}' não é numérica")
                if spec is None:
                    literals[side] = canonical_value(
                        DataType.DECIMAL, MAX_DECIMAL_SCALE, operand.value or ""
                    )
            return ColumnSpec(name=rule.name, data_type=DataType.DECIMAL, scale=expression.scale)
        case ConcatExpression():
            for part in expression.parts:
                _operand_spec(part, schema)
            return ColumnSpec(name=rule.name, data_type=DataType.TEXT)
        case DatePartExpression():
            if _column(schema, expression.column).data_type not in TEMPORAL:
                raise ValueError(f"a coluna '{expression.column}' não é de data")
            if expression.part == "year_month":
                return ColumnSpec(name=rule.name, data_type=DataType.TEXT)
            return ColumnSpec(name=rule.name, data_type=DataType.INTEGER)
        case DateDiffExpression():
            for name in (expression.start, expression.end):
                if _column(schema, name).data_type not in TEMPORAL:
                    raise ValueError(f"a coluna '{name}' não é de data")
            return ColumnSpec(name=rule.name, data_type=DataType.INTEGER)
    raise ValueError("expressão desconhecida")


def plan_rules(rules: list[Any], input_schema: list[ColumnSpec]) -> RulePlan:
    """Valida as regras na ordem e calcula o esquema após cada uma."""
    if len(rules) > MAX_RULES:
        raise RuleError(MAX_RULES, f"o limite é de {MAX_RULES} regras")
    schema = list(input_schema)
    steps: list[PlannedRule] = []
    dedup: PlannedRule | None = None
    active = [(i, r) for i, r in enumerate(rules) if r.enabled]
    for position, (index, rule) in enumerate(active):
        if isinstance(rule, DeduplicateRule) and position != len(active) - 1:
            raise RuleError(index, "a remoção de duplicidades deve ser a última regra ativa")
        try:
            new_schema, literals = _plan_one(rule, schema)
        except ValueError as exc:
            raise RuleError(index, str(exc)) from exc
        planned = PlannedRule(index=index, rule=rule, schema=schema, literals=literals)
        if isinstance(rule, DeduplicateRule):
            dedup = planned
        else:
            steps.append(planned)
        schema = new_schema
    keys = (dedup.rule.columns or [c.name for c in schema]) if dedup else []
    return RulePlan(steps=steps, output=schema, dedup=dedup, dedup_keys=keys)


# ---------------------------------------------------------------- execução por lote


@dataclass
class TransformBatch:
    frame: pl.DataFrame
    excluded: pl.DataFrame  # __df_row + metadados da exclusão
    reasons: Counter[str] = field(default_factory=Counter)
    categories: Counter[str] = field(default_factory=Counter)


EXCLUSION_SCHEMA: dict[str, pl.DataType] = {
    "__df_row": pl.Int64(),
    "__df_reason": pl.String(),
    "__df_column": pl.String(),
    "__df_detail": pl.String(),
    "__df_category": pl.String(),
    "__df_rule": pl.Int32(),
}


def _exclusions(
    rows: pl.DataFrame,
    reason: str | pl.Expr,
    column: str | pl.Expr | None,
    detail: str | pl.Expr,
    category: str,
    rule_index: int,
) -> pl.DataFrame:
    def as_expr(value: str | pl.Expr | None) -> pl.Expr:
        return value if isinstance(value, pl.Expr) else pl.lit(value, dtype=pl.String)

    return rows.select(
        pl.col("__df_row"),
        as_expr(reason).alias("__df_reason"),
        as_expr(column).alias("__df_column"),
        as_expr(detail).alias("__df_detail"),
        pl.lit(category).alias("__df_category"),
        pl.lit(rule_index + 1, dtype=pl.Int32).alias("__df_rule"),
    ).cast(EXCLUSION_SCHEMA)  # type: ignore[arg-type]


def _as_text(name: str, spec: ColumnSpec) -> pl.Expr:
    column = pl.col(name)
    match spec.data_type:
        case DataType.TEXT:
            return column
        case DataType.DATETIME:
            return column.dt.strftime("%Y-%m-%d %H:%M:%S")
        case DataType.DATE:
            return column.dt.strftime("%Y-%m-%d")
        case DataType.BOOLEAN:
            return pl.when(column).then(pl.lit("true")).when(~column).then(pl.lit("false"))
        case _:
            return column.cast(pl.String)


def _convert_expr(rule: ConvertTypeRule, spec: ColumnSpec) -> tuple[pl.Expr, pl.Expr, str]:
    """(valor convertido, motivo por linha ou nulo, detalhe)."""
    column = pl.col(spec.name)
    target = rule.target
    detail = f"Valor não converte de {type_label(spec.data_type)} para {type_label(target, rule.format)}."
    no_reason = pl.lit(None, dtype=pl.String)
    if target == DataType.TEXT:
        return _as_text(spec.name, spec), no_reason, detail
    if spec.data_type == DataType.TEXT:
        value, too_many = text_to_type(
            column, target, fmt=rule.format, scale=rule.scale,
            decimal_separator=rule.decimal_separator, thousands_separator=rule.thousands_separator,
        )  # fmt: skip
        failed = column.is_not_null() & value.is_null()
        text_reason = (
            pl.when(failed & (too_many if too_many is not None else pl.lit(False)))
            .then(pl.lit(SCALE_ERROR))
            .when(failed)
            .then(pl.lit(TYPE_ERROR))
        )
        return value, text_reason.otherwise(None), detail
    dtype = polars_dtype(target, rule.scale)
    if spec.data_type == DataType.DECIMAL and target == DataType.INTEGER:
        fractional = (column % 1) != 0
        reason = pl.when(fractional).then(pl.lit(TYPE_ERROR)).otherwise(None)
        return (
            column.cast(pl.Int64, strict=False),
            reason,
            "Valor com casas decimais não vira inteiro sem perda.",
        )
    if spec.data_type == DataType.DECIMAL and target == DataType.DECIMAL:
        converted = column.cast(dtype)
        lost = converted.cast(polars_dtype(DataType.DECIMAL, spec.scale)) != column
        reason = pl.when(lost).then(pl.lit(SCALE_ERROR)).otherwise(None)
        return (
            converted,
            reason,
            f"Valor possui mais de {rule.scale} casas decimais; não foi arredondado.",
        )
    if spec.data_type == DataType.DATETIME and target == DataType.DATE:
        has_time = column.dt.time() != pl.time(0)
        reason = pl.when(has_time).then(pl.lit(TYPE_ERROR)).otherwise(None)
        return (
            column.dt.date(),
            reason,
            "Valor tem horário; use 'Criar coluna derivada' para extrair partes da data.",
        )
    return column.cast(dtype), no_reason, detail


def _condition_expr(
    condition: Condition, spec: ColumnSpec, literals: dict[str, Any], i: int
) -> pl.Expr:
    column = pl.col(spec.name)
    op = condition.operator
    if op == "is_null":
        return column.is_null()
    if op == "not_null":
        return column.is_not_null()
    if op == "is_true":
        return column.eq(True)
    if op == "is_false":
        return column.eq(False)
    dtype = polars_dtype(spec.data_type, spec.scale)
    if op in _LIST_VALUE:
        values = literals[f"{i}:values"]
        if spec.data_type == DataType.TEXT and condition.case_insensitive:
            expr = column.str.to_lowercase().is_in([str(v).lower() for v in values])
        else:
            expr = column.is_in(pl.Series(values, dtype=dtype))
        return expr if op == "in" else ~expr
    value = literals[f"{i}:value"]
    if spec.data_type == DataType.TEXT:
        text, target = (
            (column.str.to_lowercase(), str(value).lower())
            if condition.case_insensitive
            else (column, str(value))
        )
        match op:
            case "eq":
                return text == target
            case "ne":
                return text != target
            case "contains":
                return text.str.contains(target, literal=True)
            case "not_contains":
                return ~text.str.contains(target, literal=True)
            case "starts_with":
                return text.str.starts_with(target)
            case "ends_with":
                return text.str.ends_with(target)
    lit = pl.lit(value, dtype=dtype)
    match op:
        case "eq":
            return column == lit
        case "ne":
            return column != lit
        case "gt":
            return column > lit
        case "gte":
            return column >= lit
        case "lt":
            return column < lit
        case "lte":
            return column <= lit
        case "between":
            return (column >= lit) & (column <= pl.lit(literals[f"{i}:value_to"], dtype=dtype))
    raise ValueError(f"operador inválido: {op}")


def describe_condition(condition: Condition) -> str:
    label = OPERATOR_LABELS[condition.operator]
    if condition.operator in _NO_VALUE:
        return f"{condition.column} {label}"
    if condition.operator in _LIST_VALUE:
        return f"{condition.column} {label} ({', '.join(condition.values or [])})"
    if condition.operator == "between":
        return f"{condition.column} {label} {condition.value} e {condition.value_to}"
    return f"{condition.column} {label} {condition.value}"


def _decimal_operand(
    operand: Operand, schema: list[ColumnSpec], literal: Any, scale: int
) -> pl.Expr:
    dtype = pl.Decimal(DECIMAL_PRECISION, scale)
    if operand.column is not None:
        return pl.col(operand.column).cast(dtype)
    return pl.lit(literal, dtype=pl.Decimal(DECIMAL_PRECISION, MAX_DECIMAL_SCALE)).cast(dtype)


def _derived_expr(
    rule: DerivedColumnRule, schema: list[ColumnSpec], literals: dict[str, Any]
) -> tuple[pl.Expr, pl.Expr | None]:
    """(valor, máscara de divisão por zero)."""
    expression = rule.expression
    specs = _by_name(schema)
    match expression:
        case ArithmeticExpression():
            scales = [
                specs[o.column].scale or 0
                for o in (expression.left, expression.right)
                if o.column is not None
            ]
            work = min(max([*scales, expression.scale]) + 4, MAX_DECIMAL_SCALE)
            left = _decimal_operand(expression.left, schema, literals.get("left"), work)
            right = _decimal_operand(expression.right, schema, literals.get("right"), work)
            target = pl.Decimal(DECIMAL_PRECISION, expression.scale)
            if expression.operator == "divide":
                zero = right == 0
                safe = pl.when(zero).then(None).otherwise(right)
                return (left / safe).cast(target), zero.fill_null(False)
            ops = {"add": left + right, "subtract": left - right, "multiply": left * right}
            return ops[expression.operator].cast(target), None
        case ConcatExpression():
            parts = [
                _as_text(p.column, specs[p.column]) if p.column is not None else pl.lit(p.value)
                for p in expression.parts
            ]
            return pl.concat_str(parts, separator=expression.separator, ignore_nulls=True), None
        case DatePartExpression():
            column = pl.col(expression.column)
            part = expression.part
            if part == "year_month":
                return column.dt.strftime("%Y-%m"), None
            accessor = {
                "year": column.dt.year(),
                "month": column.dt.month(),
                "day": column.dt.day(),
                "quarter": column.dt.quarter(),
                "weekday": column.dt.weekday(),  # 1 = segunda-feira
            }[part]
            return accessor.cast(pl.Int64), None
        case DateDiffExpression():
            start = pl.col(expression.start).cast(pl.Datetime("us"))
            end = pl.col(expression.end).cast(pl.Datetime("us"))
            return (end - start).dt.total_days().cast(pl.Int64), None
    raise ValueError("expressão desconhecida")


def apply_rules(frame: pl.DataFrame, plan: RulePlan) -> TransformBatch:
    """Aplica as regras (exceto a deduplicação, que é global) a um lote."""
    excluded: list[pl.DataFrame] = []
    result = TransformBatch(frame=frame, excluded=pl.DataFrame(schema=EXCLUSION_SCHEMA))

    def exclude(
        mask: pl.Expr,
        reason: str | pl.Expr,
        column: str | pl.Expr | None,
        detail: str | pl.Expr,
        category: str,
        index: int,
    ) -> None:
        marked = result.frame.with_columns(mask.fill_null(False).alias("__df_out"))
        removed = marked.filter(pl.col("__df_out"))
        if removed.height:
            rows = _exclusions(removed, reason, column, detail, category, index)
            excluded.append(rows)
            result.reasons.update(rows["__df_reason"].to_list())
            result.categories[category] += rows.height
        result.frame = marked.filter(~pl.col("__df_out")).drop("__df_out")

    for step in plan.steps:
        rule, schema, index = step.rule, step.schema, step.index
        match rule:
            case TrimRule():
                exprs = []
                for name in rule.columns:
                    expr = pl.col(name).str.strip_chars()
                    if rule.collapse_internal:
                        expr = expr.str.replace_all(r"\s+", " ")
                    exprs.append(expr.alias(name))
                result.frame = result.frame.with_columns(exprs)
            case NormalizeTextRule():
                exprs = []
                for name in rule.columns:
                    expr = pl.col(name)
                    if rule.remove_accents:
                        expr = expr.str.normalize("NFKD").str.replace_all(r"\p{M}", "")
                    exprs.append(expr.str.normalize(rule.form).alias(name))
                result.frame = result.frame.with_columns(exprs)
            case ChangeCaseRule():
                change = _CASE_CHANGES[rule.mode]
                result.frame = result.frame.with_columns(
                    change(pl.col(n)).alias(n) for n in rule.columns
                )
            case ConvertTypeRule():
                spec = _column(schema, rule.column)
                value, reason, detail = _convert_expr(rule, spec)
                marked = result.frame.with_columns(
                    reason.alias("__df_reason_tmp"), value.alias("__df_value_tmp")
                )
                result.frame = marked
                exclude(
                    pl.col("__df_reason_tmp").is_not_null(),
                    pl.col("__df_reason_tmp"),
                    rule.column,
                    detail,
                    CATEGORY_REJECTED,
                    index,
                )
                result.frame = result.frame.with_columns(
                    pl.col("__df_value_tmp").alias(rule.column)
                ).drop("__df_reason_tmp", "__df_value_tmp")
            case StandardizeDatesRule():
                column = pl.col(rule.column).str.strip_chars()
                if rule.target == "date":
                    attempts = [column.str.to_date(f, strict=False) for f in rule.formats]
                else:
                    attempts = [
                        column.str.to_datetime(f, strict=False, time_unit="us")
                        for f in rule.formats
                    ]
                value = pl.coalesce(attempts)
                labels = ", ".join(
                    DATE_FORMATS.get(f) or DATETIME_FORMATS.get(f, f) for f in rule.formats
                )
                result.frame = result.frame.with_columns(value.alias("__df_value_tmp"))
                exclude(
                    pl.col(rule.column).is_not_null() & pl.col("__df_value_tmp").is_null(),
                    TYPE_ERROR, rule.column, f"Valor não corresponde a nenhum dos formatos: {labels}.",
                    CATEGORY_REJECTED, index,
                )  # fmt: skip
                result.frame = result.frame.with_columns(
                    pl.col("__df_value_tmp").alias(rule.column)
                ).drop("__df_value_tmp")
            case FixNumbersRule():
                text = pl.col(rule.column).str.strip_chars()
                if rule.strip_currency:
                    text = text.str.replace_all(_CURRENCY, "").str.replace_all(r"[\s ]", "")
                if rule.parentheses_negative:
                    text = (
                        pl.when(text.str.contains(r"^\(.*\)$"))
                        .then(pl.lit("-") + text.str.strip_chars("()"))
                        .otherwise(text)
                    )
                target = DataType(rule.target)
                value, too_many = text_to_type(
                    text, target, fmt=None, scale=rule.scale,
                    decimal_separator=rule.decimal_separator, thousands_separator=rule.thousands_separator,
                )  # fmt: skip
                failed = pl.col(rule.column).is_not_null() & value.is_null()
                reason = (
                    pl.when(failed & (too_many if too_many is not None else pl.lit(False)))
                    .then(pl.lit(SCALE_ERROR))
                    .when(failed)
                    .then(pl.lit(TYPE_ERROR))
                    .otherwise(None)
                )
                result.frame = result.frame.with_columns(
                    reason.alias("__df_reason_tmp"), value.alias("__df_value_tmp")
                )
                exclude(
                    pl.col("__df_reason_tmp").is_not_null(), pl.col("__df_reason_tmp"), rule.column,
                    f"Valor não é um número válido no formato configurado ({type_label(target)}).",
                    CATEGORY_REJECTED, index,
                )  # fmt: skip
                result.frame = result.frame.with_columns(
                    pl.col("__df_value_tmp").alias(rule.column)
                ).drop("__df_reason_tmp", "__df_value_tmp")
            case HandleNullsRule():
                specs = _by_name(schema)
                if rule.strategy == "fill":
                    result.frame = result.frame.with_columns(
                        pl.col(name)
                        .fill_null(
                            pl.lit(
                                step.literals[name],
                                dtype=polars_dtype(specs[name].data_type, specs[name].scale),
                            )
                        )
                        .alias(name)
                        for name in rule.columns
                    )
                else:
                    first_null = pl.coalesce(
                        [pl.when(pl.col(n).is_null()).then(pl.lit(n)) for n in rule.columns]
                    )
                    exclude(
                        first_null.is_not_null(), NULL_ERROR, first_null,
                        "Valor nulo em coluna configurada para rejeitar nulos.", CATEGORY_REJECTED, index,
                    )  # fmt: skip
            case RemoveEmptyRowsRule():
                empties = [
                    pl.col(c.name).is_null() | (pl.col(c.name).str.strip_chars() == "")
                    if c.data_type == DataType.TEXT
                    else pl.col(c.name).is_null()
                    for c in schema
                ]
                exclude(
                    pl.all_horizontal(empties), EMPTY_ROW_ERROR, None,
                    "Registro sem nenhum valor preenchido.", CATEGORY_REJECTED, index,
                )  # fmt: skip
            case FilterRowsRule():
                specs = _by_name(schema)
                conditions = [
                    _condition_expr(c, specs[c.column], step.literals, i).fill_null(False)
                    for i, c in enumerate(rule.conditions)
                ]
                keep = (
                    pl.all_horizontal(conditions)
                    if rule.match == "all"
                    else pl.any_horizontal(conditions)
                )
                joiner = " e " if rule.match == "all" else " ou "
                description = joiner.join(describe_condition(c) for c in rule.conditions)
                exclude(
                    ~keep, FILTER_REASON, None, f"Não atende ao filtro: {description}.",
                    CATEGORY_FILTERED, index,
                )  # fmt: skip
            case RenameColumnsRule():
                result.frame = result.frame.rename(rule.mapping)
            case DerivedColumnRule():
                value, zero = _derived_expr(rule, schema, step.literals)
                if zero is not None:
                    exclude(
                        zero, DIVISION_ERROR, rule.name,
                        "Divisão por zero ao calcular a coluna derivada.", CATEGORY_REJECTED, index,
                    )  # fmt: skip
                result.frame = result.frame.with_columns(value.alias(rule.name))

    if excluded:
        result.excluded = pl.concat(excluded, how="vertical")
    return result


def mark_duplicates(frame: pl.LazyFrame, plan: RulePlan) -> pl.LazyFrame:
    """Marca o registro mantido de cada chave (__df_keep) e qual é ele (__df_kept_row).

    Nulos contam como valores iguais entre si — a mesma regra do GROUP BY da análise em DuckDB.
    """
    assert plan.dedup is not None
    keys = plan.dedup_keys
    keep_first = plan.dedup.rule.keep == "first"
    distinct = (
        pl.struct(keys).is_first_distinct() if keep_first else pl.struct(keys).is_last_distinct()
    )
    kept_row = pl.col("__df_row").first() if keep_first else pl.col("__df_row").last()
    return frame.with_columns(
        distinct.alias("__df_keep"), kept_row.over(keys).alias("__df_kept_row")
    )


def duplicate_exclusions(duplicates: pl.DataFrame, plan: RulePlan) -> pl.DataFrame:
    """Metadados de exclusão para os registros descartados (colunas __df_row e __df_kept_row)."""
    assert plan.dedup is not None
    return duplicates.select(
        pl.col("__df_row"),
        pl.lit(DUPLICATE_REASON).alias("__df_reason"),
        pl.lit(None, dtype=pl.String).alias("__df_column"),
        pl.format(
            "Duplicado do registro {} pela chave ({}).",
            pl.col("__df_kept_row"),
            pl.lit(", ".join(plan.dedup_keys)),
        ).alias("__df_detail"),
        pl.lit(CATEGORY_DUPLICATE).alias("__df_category"),
        pl.lit(plan.dedup.index + 1, dtype=pl.Int32).alias("__df_rule"),
        pl.col("__df_kept_row").alias("__df_duplicate_of"),
    )


def resolve_rules(raw: list[dict[str, Any]]) -> list[Any]:
    """Valida o JSON das regras (formato) — a validação contra o esquema é plan_rules."""
    return RULES_ADAPTER.validate_python(raw)


def rules_to_json(rules: list[Any]) -> list[dict[str, Any]]:
    return [rule.model_dump(mode="json") for rule in rules]


__all__ = [
    "DIVISION_ERROR",
    "DUPLICATE_REASON",
    "EMPTY_ROW_ERROR",
    "FILTER_REASON",
    "NULL_ERROR",
    "REQUIRED_ERROR",
    "RULE_LABELS",
    "RuleError",
    "RulePlan",
    "apply_rules",
    "duplicate_exclusions",
    "mark_duplicates",
    "plan_rules",
    "resolve_rules",
    "rules_to_json",
]
