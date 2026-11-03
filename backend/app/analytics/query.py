"""Consultas controladas com DuckDB sobre Parquet.

Não existe SQL vindo do usuário: identificadores são validados contra o esquema conhecido da
versão e citados com escaping; valores são sempre parâmetros.
"""

import datetime as dt
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import duckdb

from app.core.errors import ValidationFailed
from app.processing.transforms import (
    LIST_OPERATORS,
    NO_VALUE_OPERATORS,
    OPERATOR_LABELS,
    OPERATORS_BY_TYPE,
    Condition,
    literal_for,
)
from app.processing.types import ColumnSpec, DataType

JS_SAFE_INT = 2**53 - 1
MAX_FILTERS = 20
MAX_SEARCH_LENGTH = 100
QUERY_TIMEOUT_SECONDS = 10.0


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sandboxed_connection(allowed_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    # Limites de recursos e sandbox: só o diretório de cache pode ser lido, sem rede,
    # e a configuração fica travada para a sessão.
    con.execute("SET threads = 2")
    con.execute("SET memory_limit = '512MB'")
    con.execute("SET allowed_directories = ?", [[str(allowed_dir)]])
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def to_json_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value if abs(value) <= JS_SAFE_INT else str(value)
    if isinstance(value, Decimal):
        return format(value, "f")  # preserva a precisão: decimal trafega como texto
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, float):
        return value
    return str(value)


@dataclass
class Page:
    columns: list[str]
    rows: list[list[Any]]


@dataclass
class WhereClause:
    """Condição SQL montada pelo backend: identificadores validados, valores em `params`."""

    sql: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def apply(self) -> str:
        return f" WHERE {self.sql}" if self.sql else ""


def combine_where(*clauses: WhereClause) -> WhereClause:
    """Junta cláusulas com E. Os nomes de parâmetro precisam ser distintos (prefixos)."""
    parts = [c for c in clauses if c.sql]
    params: dict[str, Any] = {}
    for clause in parts:
        clash = params.keys() & clause.params.keys()
        assert not clash, f"parâmetros repetidos: {clash}"
        params.update(clause.params)
    return WhereClause(sql=" AND ".join(f"({c.sql})" for c in parts), params=params)


_COMPARISON = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _condition_sql(
    condition: Condition, spec: ColumnSpec, param: str
) -> tuple[str, dict[str, Any]]:
    column = quote_identifier(spec.name)
    operator = condition.operator
    if operator in NO_VALUE_OPERATORS:
        return {
            "is_null": f"{column} IS NULL",
            "not_null": f"{column} IS NOT NULL",
            "is_true": f"{column} IS TRUE",
            "is_false": f"{column} IS FALSE",
        }[operator], {}
    fold = spec.data_type == DataType.TEXT and condition.case_insensitive
    target = f"lower({column})" if fold else column

    def literal(text: str | None) -> Any:
        value = literal_for(spec, text)
        return value.lower() if fold and isinstance(value, str) else value

    if operator in LIST_OPERATORS:
        values = [literal(v) for v in condition.values or []]
        if not values:
            raise ValueError("informe ao menos um valor para a lista")
        negate = "NOT " if operator == "not_in" else ""
        return f"{negate}list_contains(${param}, {target})", {param: values}
    if operator == "between":
        low, high = f"{param}a", f"{param}b"
        return (
            f"{target} BETWEEN ${low} AND ${high}",
            {low: literal(condition.value), high: literal(condition.value_to)},
        )
    value = literal(condition.value)
    if operator in _COMPARISON:
        return f"{target} {_COMPARISON[operator]} ${param}", {param: value}
    function = {"contains": "contains", "not_contains": "contains"}.get(operator, operator)
    negate = "NOT " if operator == "not_contains" else ""
    return f"{negate}{function}({target}, ${param})", {param: value}


def build_where(
    conditions: list[Condition],
    match: Literal["all", "any"],
    search: str | None,
    schema: list[ColumnSpec],
    *,
    prefix: str = "f",
    label: str = "Filtro",
) -> WhereClause:
    """Filtros tipados e busca textual. Erros citam a posição do filtro (1-based).

    `prefix` separa os nomes de parâmetro quando várias cláusulas são combinadas, e `label`
    diz na mensagem de erro de qual grupo de filtros se trata.
    """
    if len(conditions) > MAX_FILTERS:
        raise ValidationFailed(f"Use no máximo {MAX_FILTERS} filtros por consulta.")
    by_name = {c.name: c for c in schema}
    parts: list[str] = []
    params: dict[str, Any] = {}
    for index, condition in enumerate(conditions):
        spec = by_name.get(condition.column)
        position = index + 1
        if spec is None:
            raise ValidationFailed(
                f"{label} {position}: coluna desconhecida.",
                code="invalid_filter",
                details={"filter_index": index},
            )
        if condition.operator not in OPERATORS_BY_TYPE[spec.data_type]:
            raise ValidationFailed(
                f"{label} {position}: o operador '{OPERATOR_LABELS[condition.operator]}' "
                f"não se aplica à coluna '{spec.name}'.",
                code="invalid_filter",
                details={"filter_index": index},
            )
        try:
            sql, values = _condition_sql(condition, spec, f"{prefix}{index}")
        except ValueError as exc:
            raise ValidationFailed(
                f"{label} {position}: {exc}",
                code="invalid_filter",
                details={"filter_index": index},
            ) from exc
        parts.append(f"({sql})")
        params.update(values)

    clauses = []
    if parts:
        clauses.append("(" + (" AND " if match == "all" else " OR ").join(parts) + ")")
    term = (search or "").strip()
    if term:
        if len(term) > MAX_SEARCH_LENGTH:
            raise ValidationFailed(f"A busca aceita até {MAX_SEARCH_LENGTH} caracteres.")
        text_columns = [c for c in schema if c.data_type == DataType.TEXT]
        if not text_columns:
            raise ValidationFailed(
                "Esta versão não tem colunas de texto para buscar.", code="search_unavailable"
            )
        # contains() compara o texto literal: % e _ não são curingas.
        clauses.append(
            "("
            + " OR ".join(
                f"contains(lower({quote_identifier(c.name)}), $search)" for c in text_columns
            )
            + ")"
        )
        params["search"] = term.lower()
    return WhereClause(sql=" AND ".join(clauses), params=params)


def run_limited(
    con: duckdb.DuckDBPyConnection, sql: str, params: dict[str, Any]
) -> list[tuple[Any, ...]]:
    """Executa com tempo-limite: consultas que passarem dele são interrompidas."""
    timer = threading.Timer(QUERY_TIMEOUT_SECONDS, con.interrupt)
    timer.start()
    try:
        return con.execute(sql, params).fetchall()
    except duckdb.InterruptException as exc:
        raise ValidationFailed(
            f"A consulta excedeu o tempo limite de {QUERY_TIMEOUT_SECONDS:.0f} s. "
            "Use filtros mais específicos ou menos colunas.",
            code="query_timeout",
        ) from exc
    finally:
        timer.cancel()


def count_rows(path: Path, where: WhereClause) -> int:
    con = sandboxed_connection(path.parent)
    try:
        rows = run_limited(
            con,
            f"SELECT count(*) FROM read_parquet($path){where.apply()}",  # noqa: S608 - montado pelo backend
            {"path": str(path), **where.params},
        )
    finally:
        con.close()
    return int(rows[0][0])


def fetch_page(
    path: Path,
    allowed_columns: list[str],
    *,
    columns: list[str] | None,
    sort: str | None,
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
    tiebreak: str = "__df_row",
    where: WhereClause | None = None,
) -> Page:
    selected = columns or allowed_columns
    unknown = [c for c in selected if c not in allowed_columns]
    if unknown:
        raise ValidationFailed("Coluna desconhecida na consulta.", details={"columns": unknown})
    if sort is not None and sort not in allowed_columns:
        raise ValidationFailed("Coluna de ordenação desconhecida.", details={"sort": sort})

    select_sql = ", ".join(quote_identifier(c) for c in selected)
    order = []
    if sort:
        order.append(
            f"{quote_identifier(sort)} {'DESC' if direction == 'desc' else 'ASC'} NULLS LAST"
        )
    order.append(quote_identifier(tiebreak))
    where = where or WhereClause()
    sql = (
        f"SELECT {select_sql} FROM read_parquet($path){where.apply()} "  # noqa: S608 - identificadores validados
        f"ORDER BY {', '.join(order)} LIMIT $limit OFFSET $offset"
    )
    con = sandboxed_connection(path.parent)
    try:
        found = run_limited(
            con, sql, {"path": str(path), "limit": limit, "offset": offset, **where.params}
        )
        rows = [[to_json_value(v) for v in row] for row in found]
    finally:
        con.close()
    return Page(columns=selected, rows=rows)


@dataclass
class DuplicateSummary:
    total_rows: int
    distinct_keys: int
    duplicate_rows: int
    groups_with_duplicates: int
    top_groups: list[dict[str, Any]]


def duplicate_summary(path: Path, keys: list[str], *, top: int = 20) -> DuplicateSummary:
    """Duplicidades da versão inteira pela chave escolhida (NULL agrupa com NULL)."""
    columns = ", ".join(quote_identifier(k) for k in keys)
    grouped = (
        f"SELECT {columns}, COUNT(*) AS n, MIN(__df_row) AS first_row, MAX(__df_row) AS last_row, "  # noqa: S608 - identificadores validados
        f"list(__df_row ORDER BY __df_row)[1:10] AS sample_rows "
        f"FROM read_parquet($path) GROUP BY {columns}"
    )
    con = sandboxed_connection(path.parent)
    try:
        totals = con.execute(
            f"WITH g AS ({grouped}) SELECT COALESCE(SUM(n), 0), COUNT(*), "  # noqa: S608
            "COALESCE(SUM(n - 1), 0), COUNT(*) FILTER (WHERE n > 1) FROM g",
            {"path": str(path)},
        ).fetchone()
        assert totals is not None
        top_rows = con.execute(
            f"WITH g AS ({grouped}) SELECT * FROM g WHERE n > 1 "  # noqa: S608
            "ORDER BY n DESC, first_row LIMIT $top",
            {"path": str(path), "top": top},
        ).fetchall()
    finally:
        con.close()
    width = len(keys)
    groups = [
        {
            "key": [to_json_value(v) for v in row[:width]],
            "count": int(row[width]),
            "first_row": int(row[width + 1]),
            "last_row": int(row[width + 2]),
            "sample_rows": [int(r) for r in row[width + 3]],
        }
        for row in top_rows
    ]
    return DuplicateSummary(
        total_rows=int(totals[0]),
        distinct_keys=int(totals[1]),
        duplicate_rows=int(totals[2]),
        groups_with_duplicates=int(totals[3]),
        top_groups=groups,
    )
