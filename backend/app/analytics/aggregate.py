"""Consultas analíticas (KPIs e gráficos) com DuckDB sobre o Parquet de uma versão.

O cliente escolhe colunas e operações de listas fechadas: agregações, granularidades de data,
ordenação e filtros tipados (os mesmos do explorer). O SQL é montado aqui, com identificadores
validados contra o esquema da versão e valores sempre como parâmetros. Nenhuma coluna numérica
é tratada como dinheiro: o resultado diz apenas o tipo e a escala de cada medida.
"""

import datetime as dt
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.query import (
    MAX_FILTERS,
    WhereClause,
    build_where,
    combine_where,
    quote_identifier,
    run_limited,
    sandboxed_connection,
    to_json_value,
)
from app.core.errors import ValidationFailed
from app.processing.transforms import Condition
from app.processing.types import MAX_DECIMAL_SCALE, ColumnSpec, DataType

Aggregation = Literal["count", "count_distinct", "sum", "avg", "min", "max"]
Granularity = Literal["day", "week", "month", "quarter", "year"]

MAX_METRICS = 6
MAX_GROUPS = 100
# Séries temporais não são cortadas (um corte esconderia parte do período): acima disso,
# a consulta pede uma granularidade maior.
MAX_POINTS = 1000
MAX_PERIOD_DAYS = 3660

NUMERIC = {DataType.INTEGER, DataType.DECIMAL}
TEMPORAL = {DataType.DATE, DataType.DATETIME}
_ORDERABLE = NUMERIC | TEMPORAL
DIMENSION_TYPES = {DataType.TEXT, DataType.BOOLEAN, DataType.INTEGER, *TEMPORAL}

AGGREGATION_LABELS = {
    "count": "Contagem",
    "count_distinct": "Contagem distinta",
    "sum": "Soma",
    "avg": "Média",
    "min": "Mínimo",
    "max": "Máximo",
}
GRANULARITY_LABELS = {
    "day": "dia",
    "week": "semana",
    "month": "mês",
    "quarter": "trimestre",
    "year": "ano",
}
# Casas extras da média em relação à escala da coluna.
AVG_EXTRA_SCALE = 2


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aggregation: Aggregation
    # Sem coluna, "count" conta registros; nas demais agregações a coluna é obrigatória.
    column: str | None = Field(default=None, max_length=63)


class Dimension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=63)
    # Só para colunas de data; sem valor, datas são agrupadas por mês.
    granularity: Granularity | None = None


class PeriodComparison(BaseModel):
    """Período atual (datas inclusivas) comparado ao anterior de mesma duração ou ao do ano
    anterior."""

    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=63)
    start: dt.date
    end: dt.date
    mode: Literal["previous_period", "previous_year"] = "previous_period"

    @model_validator(mode="after")
    def _range(self) -> "PeriodComparison":
        if self.end < self.start:
            raise ValueError("o fim do período não pode ser anterior ao início")
        if (self.end - self.start).days + 1 > MAX_PERIOD_DAYS:
            raise ValueError(f"o período pode ter no máximo {MAX_PERIOD_DAYS} dias")
        return self


class AggregateSpec(BaseModel):
    """O que calcular: medidas, dimensão opcional, filtros, ordenação e comparação."""

    model_config = ConfigDict(extra="forbid")
    metrics: list[Metric] = Field(min_length=1, max_length=MAX_METRICS)
    dimension: Dimension | None = None
    filters: list[Condition] = Field(default_factory=list, max_length=MAX_FILTERS)
    match: Literal["all", "any"] = "all"
    sort: Literal["metric", "dimension"] | None = None
    direction: Literal["asc", "desc"] | None = None
    limit: int = Field(default=10, ge=1, le=MAX_GROUPS)
    comparison: PeriodComparison | None = None


# ---------------------------------------------------------------- plano


@dataclass(frozen=True)
class MetricPlan:
    key: str
    aggregation: str
    column: str | None
    label: str
    data_type: DataType  # tipo do resultado, não da coluna
    scale: int | None

    def sql(self, only: str | None = None) -> str:
        """Expressão de agregação; `only` restringe os registros (FILTER do SQL)."""
        filt = f" FILTER (WHERE {only})" if only else ""
        target = quote_identifier(self.column) if self.column else "*"
        match self.aggregation:
            case "count":
                return f"count({target}){filt}"
            case "count_distinct":
                return f"count(DISTINCT {target}){filt}"
            case "avg":
                return f"CAST(avg({target}){filt} AS DECIMAL(38, {self.scale}))"
            case aggregation:  # sum, min, max
                return f"{aggregation}({target}){filt}"


@dataclass(frozen=True)
class DimensionPlan:
    column: str
    data_type: DataType
    granularity: str | None

    @property
    def temporal(self) -> bool:
        return self.granularity is not None

    def sql(self) -> str:
        column = quote_identifier(self.column)
        if self.granularity is None:
            return column
        # date_trunc devolve TIMESTAMP; o grupo é sempre o primeiro dia do intervalo.
        return f"CAST(date_trunc('{self.granularity}', {column}) AS DATE)"


@dataclass(frozen=True)
class Period:
    start: dt.date
    end: dt.date


@dataclass(frozen=True)
class ComparisonPlan:
    column: str
    mode: str
    current: Period
    previous: Period
    current_sql: str
    previous_sql: str

    def params(self) -> dict[str, Any]:
        return {
            "cmp_cs": self.current.start,
            "cmp_ce": self.current.end,
            "cmp_ps": self.previous.start,
            "cmp_pe": self.previous.end,
        }


@dataclass(frozen=True)
class AggregatePlan:
    metrics: list[MetricPlan]
    dimension: DimensionPlan | None
    where: WhereClause
    sort: str
    direction: str
    limit: int
    comparison: ComparisonPlan | None


def _invalid(message: str, code: str, **details: Any) -> ValidationFailed:
    return ValidationFailed(message, code=code, details=details or None)


def _metric_plan(index: int, metric: Metric, by_name: dict[str, ColumnSpec]) -> MetricPlan:
    position = index + 1
    aggregation = metric.aggregation
    label = AGGREGATION_LABELS[aggregation]
    if metric.column is None:
        if aggregation != "count":
            raise _invalid(
                f"Medida {position}: escolha a coluna para '{label.lower()}'.",
                "invalid_metric",
                metric_index=index,
            )
        return MetricPlan(f"m{index}", aggregation, None, "Registros", DataType.INTEGER, None)
    spec = by_name.get(metric.column)
    if spec is None:
        raise _invalid(
            f"Medida {position}: coluna desconhecida.", "invalid_metric", metric_index=index
        )
    name = spec.name
    data_type, scale = spec.data_type, spec.scale
    allowed = {
        "count": set(DataType),
        "count_distinct": set(DataType),
        "sum": NUMERIC,
        "avg": NUMERIC,
        "min": _ORDERABLE,
        "max": _ORDERABLE,
    }[aggregation]
    if data_type not in allowed:
        raise _invalid(
            f"Medida {position}: '{label.lower()}' não se aplica à coluna '{name}' "
            f"(tipo {data_type.value}).",
            "invalid_metric",
            metric_index=index,
        )
    match aggregation:
        case "count":
            return MetricPlan(
                f"m{index}", aggregation, name, f"Valores de {name}", DataType.INTEGER, None
            )
        case "count_distinct":
            return MetricPlan(
                f"m{index}", aggregation, name, f"Distintos de {name}", DataType.INTEGER, None
            )
        case "avg":
            avg_scale = min((scale or 0) + AVG_EXTRA_SCALE, MAX_DECIMAL_SCALE)
            return MetricPlan(
                f"m{index}", aggregation, name, f"Média de {name}", DataType.DECIMAL, avg_scale
            )
        case _:
            return MetricPlan(
                f"m{index}", aggregation, name, f"{label} de {name}", data_type, scale
            )


def _dimension_plan(dimension: Dimension, by_name: dict[str, ColumnSpec]) -> DimensionPlan:
    spec = by_name.get(dimension.column)
    if spec is None:
        raise _invalid("Dimensão: coluna desconhecida.", "invalid_dimension")
    if spec.data_type not in DIMENSION_TYPES:
        raise _invalid(
            f"A coluna '{spec.name}' tem valores contínuos e não serve como dimensão; "
            "use um filtro de faixa de valores.",
            "invalid_dimension",
        )
    temporal = spec.data_type in TEMPORAL
    if dimension.granularity is not None and not temporal:
        raise _invalid(
            f"A granularidade só se aplica a colunas de data; '{spec.name}' não é.",
            "invalid_dimension",
        )
    granularity = (dimension.granularity or "month") if temporal else None
    return DimensionPlan(spec.name, spec.data_type, granularity)


def _shift_year(day: dt.date) -> dt.date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29/02 → 28/02
        return day.replace(year=day.year - 1, day=28)


def previous_period(comparison: PeriodComparison) -> Period:
    if comparison.mode == "previous_year":
        return Period(_shift_year(comparison.start), _shift_year(comparison.end))
    length = (comparison.end - comparison.start).days + 1
    end = comparison.start - dt.timedelta(days=1)
    return Period(end - dt.timedelta(days=length - 1), end)


def _comparison_plan(
    comparison: PeriodComparison, by_name: dict[str, ColumnSpec]
) -> ComparisonPlan:
    spec = by_name.get(comparison.column)
    if spec is None:
        raise _invalid("Comparação: coluna de data desconhecida.", "invalid_comparison")
    if spec.data_type not in TEMPORAL:
        raise _invalid(f"Comparação: a coluna '{spec.name}' não é de data.", "invalid_comparison")
    column = quote_identifier(spec.name)
    target = column if spec.data_type == DataType.DATE else f"CAST({column} AS DATE)"
    return ComparisonPlan(
        column=spec.name,
        mode=comparison.mode,
        current=Period(comparison.start, comparison.end),
        previous=previous_period(comparison),
        current_sql=f"{target} BETWEEN $cmp_cs AND $cmp_ce",
        previous_sql=f"{target} BETWEEN $cmp_ps AND $cmp_pe",
    )


def plan_aggregate(
    spec: AggregateSpec, schema: list[ColumnSpec], *, extra: tuple[WhereClause, ...] = ()
) -> AggregatePlan:
    """Valida a consulta contra o esquema e monta o plano. `extra` são filtros já validados
    (do dashboard ou da tela), combinados com E aos filtros da própria consulta."""
    by_name = {c.name: c for c in schema}
    metrics = [_metric_plan(i, m, by_name) for i, m in enumerate(spec.metrics)]
    dimension = _dimension_plan(spec.dimension, by_name) if spec.dimension else None
    comparison = _comparison_plan(spec.comparison, by_name) if spec.comparison else None
    if comparison and dimension and dimension.temporal:
        raise _invalid(
            "A comparação entre períodos não se aplica a uma dimensão de data; "
            "use uma dimensão de categoria ou nenhuma.",
            "invalid_comparison",
        )
    own = build_where(spec.filters, spec.match, None, schema, prefix="q")
    where = combine_where(own, *extra)
    if comparison:
        where = combine_where(
            where,
            WhereClause(
                sql=f"({comparison.current_sql}) OR ({comparison.previous_sql})",
                params=comparison.params(),
            ),
        )
    if dimension and dimension.temporal:
        sort, direction = "dimension", "asc"  # séries temporais em ordem cronológica
    else:
        sort = spec.sort or "metric"
        direction = spec.direction or ("desc" if sort == "metric" else "asc")
    return AggregatePlan(
        metrics=metrics,
        dimension=dimension,
        where=where,
        sort=sort,
        direction=direction,
        limit=spec.limit,
        comparison=comparison,
    )


# ---------------------------------------------------------------- execução


@dataclass
class MetricInfo:
    key: str
    aggregation: str
    column: str | None
    label: str
    data_type: str
    scale: int | None


@dataclass
class DimensionInfo:
    column: str
    data_type: str
    granularity: str | None


@dataclass
class ComparisonInfo:
    column: str
    mode: str
    current_start: dt.date
    current_end: dt.date
    previous_start: dt.date
    previous_end: dt.date
    previous_rows: int


@dataclass
class GroupRow:
    key: Any
    values: list[Any]
    previous: list[Any] | None = None


@dataclass
class OthersRow:
    groups: int
    values: list[Any]
    previous: list[Any] | None = None


@dataclass
class AggregateResult:
    metrics: list[MetricInfo]
    dimension: DimensionInfo | None
    rows: list[GroupRow]
    matched_rows: int  # registros considerados (no período atual, quando há comparação)
    total_groups: int | None
    others: OthersRow | None
    comparison: ComparisonInfo | None
    duration_ms: int = 0


def _value_columns(plan: AggregatePlan) -> list[str]:
    """Colunas de valor: m0, m1… e, com comparação, m0_p, m1_p… do período anterior."""
    current = plan.comparison.current_sql if plan.comparison else None
    columns = [f"{m.sql(current)} AS {m.key}" for m in plan.metrics]
    if plan.comparison:
        columns += [f"{m.sql(plan.comparison.previous_sql)} AS {m.key}_p" for m in plan.metrics]
        columns.append(f"count(*) FILTER (WHERE {plan.comparison.current_sql}) AS __df_n")
        columns.append(f"count(*) FILTER (WHERE {plan.comparison.previous_sql}) AS __df_np")
    else:
        columns.append("count(*) AS __df_n")
    return columns


def _split(plan: AggregatePlan, values: tuple[Any, ...]) -> tuple[list[Any], list[Any] | None]:
    width = len(plan.metrics)
    current = [to_json_value(v) for v in values[:width]]
    previous = [to_json_value(v) for v in values[width : 2 * width]] if plan.comparison else None
    return current, previous


def run_aggregate(path: Path, plan: AggregatePlan) -> AggregateResult:
    started = time.perf_counter()
    params: dict[str, Any] = {"path": str(path), **plan.where.params}
    columns = ", ".join(_value_columns(plan))
    source = f"read_parquet($path){plan.where.apply()}"
    previous_rows = 0
    con = sandboxed_connection(path.parent)
    try:
        if plan.dimension is None:
            row = run_limited(con, f"SELECT {columns} FROM {source}", params)[0]  # noqa: S608 - montado pelo backend
            current, previous = _split(plan, row)
            width = len(plan.metrics) * (2 if plan.comparison else 1)
            matched = int(row[width])
            previous_rows = int(row[width + 1]) if plan.comparison else 0
            rows = [GroupRow(key=None, values=current, previous=previous)]
            total_groups, others = None, None
        else:
            rows, matched, previous_rows, total_groups, others = _grouped(
                con, plan, params, columns
            )
    finally:
        con.close()
    return AggregateResult(
        metrics=[
            MetricInfo(m.key, m.aggregation, m.column, m.label, m.data_type.value, m.scale)
            for m in plan.metrics
        ],
        dimension=DimensionInfo(
            plan.dimension.column, plan.dimension.data_type.value, plan.dimension.granularity
        )
        if plan.dimension
        else None,
        rows=rows,
        matched_rows=matched,
        total_groups=total_groups,
        others=others,
        comparison=ComparisonInfo(
            column=plan.comparison.column,
            mode=plan.comparison.mode,
            current_start=plan.comparison.current.start,
            current_end=plan.comparison.current.end,
            previous_start=plan.comparison.previous.start,
            previous_end=plan.comparison.previous.end,
            previous_rows=previous_rows,
        )
        if plan.comparison
        else None,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _grouped(
    con: duckdb.DuckDBPyConnection, plan: AggregatePlan, params: dict[str, Any], columns: str
) -> tuple[list[GroupRow], int, int, int, OthersRow | None]:
    assert plan.dimension is not None
    direction = "DESC" if plan.direction == "desc" else "ASC"
    if plan.sort == "metric":
        order = f"m0 {direction} NULLS LAST, __df_dim ASC NULLS LAST"
    else:
        order = f"__df_dim {direction} NULLS LAST"
    source = (
        f"SELECT {plan.dimension.sql()} AS __df_dim, * FROM read_parquet($path){plan.where.apply()}"  # noqa: S608 - montado pelo backend
    )
    grouped = f"SELECT __df_dim, {columns} FROM src GROUP BY __df_dim"  # noqa: S608
    # Séries temporais buscam um ponto a mais que o limite só para detectar o excesso.
    limit = MAX_POINTS + 1 if plan.dimension.temporal else plan.limit
    extra_totals = ", sum(__df_np) OVER () AS __df_total_p" if plan.comparison else ""
    found = run_limited(
        con,
        f"WITH src AS ({source}), g AS ({grouped}) "  # noqa: S608
        f"SELECT *, count(*) OVER () AS __df_groups, sum(__df_n) OVER () AS __df_total"
        f"{extra_totals} FROM g ORDER BY {order} LIMIT $limit",
        {**params, "limit": limit},
    )
    if not found:
        return [], 0, 0, 0, None
    width = len(plan.metrics) * (2 if plan.comparison else 1)
    first = found[0]
    total_groups = int(first[width + (3 if plan.comparison else 2)])
    matched = int(first[width + (4 if plan.comparison else 3)])
    previous_rows = int(first[width + 5]) if plan.comparison else 0
    if plan.dimension.temporal and total_groups > MAX_POINTS:
        raise _invalid(
            f"A série teria {total_groups} pontos (máximo {MAX_POINTS}). "
            f"Use uma granularidade maior que {GRANULARITY_LABELS[plan.dimension.granularity or 'day']}.",
            "too_many_points",
            points=total_groups,
        )
    rows = []
    for record in found:
        current, previous = _split(plan, record[1:])
        rows.append(GroupRow(key=to_json_value(record[0]), values=current, previous=previous))
    others = None
    if not plan.dimension.temporal and total_groups > plan.limit:
        rest = run_limited(
            con,
            f"WITH src AS ({source}), g AS ({grouped}), "  # noqa: S608
            f"top AS (SELECT __df_dim FROM g ORDER BY {order} LIMIT $limit) "
            f"SELECT {columns} FROM src WHERE NOT EXISTS "
            "(SELECT 1 FROM top WHERE top.__df_dim IS NOT DISTINCT FROM src.__df_dim)",
            {**params, "limit": plan.limit},
        )[0]
        current, previous = _split(plan, rest)
        others = OthersRow(groups=total_groups - plan.limit, values=current, previous=previous)
    return rows, matched, previous_rows, total_groups, others
