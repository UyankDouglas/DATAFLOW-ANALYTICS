"""Consultas controladas com DuckDB sobre Parquet.

Não existe SQL vindo do usuário: identificadores são validados contra o esquema conhecido da
versão e citados com escaping; valores são sempre parâmetros.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import duckdb

from app.core.errors import ValidationFailed

JS_SAFE_INT = 2**53 - 1


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect(allowed_dir: Path) -> duckdb.DuckDBPyConnection:
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
    sql = (
        f"SELECT {select_sql} FROM read_parquet($path) "  # noqa: S608 - identificadores validados
        f"ORDER BY {', '.join(order)} LIMIT $limit OFFSET $offset"
    )
    con = _connect(path.parent)
    try:
        result = con.execute(sql, {"path": str(path), "limit": limit, "offset": offset})
        rows = [[to_json_value(v) for v in row] for row in result.fetchall()]
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
    con = _connect(path.parent)
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
