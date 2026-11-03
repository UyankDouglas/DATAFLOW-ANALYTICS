"""Relatório de qualidade de uma versão: indicadores, perfil das colunas e nota de 0 a 100.

Calculado com DuckDB sobre o Parquet da versão (válidos) e o `rejected.parquet` (exclusões),
sem banco nem rede. A fórmula está em `docs/quality.md`; mudar pesos ou componentes exige
incrementar `FORMULA_VERSION`, porque relatórios antigos guardam a versão com que foram feitos.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from app.analytics.query import (
    duplicate_summary,
    quote_identifier,
    sandboxed_connection,
    to_json_value,
)

FORMULA_VERSION = "1.0"
WEIGHTS = {"validity": 0.4, "completeness": 0.4, "uniqueness": 0.2}
_RANGE_TYPES = {"integer", "decimal", "date", "datetime"}


@dataclass
class IssueGroup:
    category: str
    reason: str
    column: str | None
    rule: int | None
    count: int
    example_row: int | None


@dataclass
class QualityResult:
    score: float | None
    metrics: dict[str, Any]
    issues: list[IssueGroup] = field(default_factory=list)
    duration_ms: int = 0


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_from(components: dict[str, float | None], valid: int, rejected: int) -> float | None:
    """Nota = 100 × (0,4·validade + 0,4·completude + 0,2·unicidade), com uma casa decimal.

    Sem registros publicáveis (válidos + rejeitados = 0) não há o que avaliar: nota nula.
    Com todos rejeitados (nenhum válido), completude e unicidade não existem e a nota é 0.
    """
    if valid + rejected == 0:
        return None
    if valid == 0:
        return 0.0
    total = sum(WEIGHTS[name] * (components[name] or 0.0) for name in WEIGHTS)
    return round(100 * total, 1)


def _profile(path: Path, schema: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    selects = ["count(*) AS total"]
    for i, column in enumerate(schema):
        name = quote_identifier(column["name"])
        selects += [f"count({name}) AS nn{i}", f"count(DISTINCT {name}) AS d{i}"]
        if column["data_type"] in _RANGE_TYPES:
            selects += [f"min({name}) AS mn{i}", f"max({name}) AS mx{i}"]
    con = sandboxed_connection(path.parent)
    try:
        cursor = con.execute(
            f"SELECT {', '.join(selects)} FROM read_parquet($path)",  # noqa: S608 - identificadores do esquema
            {"path": str(path)},
        )
        names = [d[0] for d in cursor.description]
        row = dict(zip(names, cursor.fetchone() or (), strict=True))
    finally:
        con.close()
    total = int(row["total"])
    columns = []
    for i, column in enumerate(schema):
        non_null = int(row[f"nn{i}"])
        columns.append(
            {
                "name": column["name"],
                "data_type": column["data_type"],
                "non_null": non_null,
                "nulls": total - non_null,
                "completeness": _ratio(non_null, total),
                "distinct": int(row[f"d{i}"]),
                "min": to_json_value(row.get(f"mn{i}")),
                "max": to_json_value(row.get(f"mx{i}")),
                "issues": 0,
            }
        )
    return total, columns


def _null_distribution(path: Path, schema: list[dict[str, Any]]) -> list[dict[str, int]]:
    """Quantos registros têm 0, 1, 2… colunas nulas."""
    flags = " + ".join(f"({quote_identifier(c['name'])} IS NULL)::INTEGER" for c in schema)
    con = sandboxed_connection(path.parent)
    try:
        rows = con.execute(
            f"SELECT nulls, count(*) FROM (SELECT {flags} AS nulls FROM read_parquet($path)) "  # noqa: S608
            "GROUP BY nulls ORDER BY nulls",
            {"path": str(path)},
        ).fetchall()
    finally:
        con.close()
    return [{"nulls": int(n), "rows": int(c)} for n, c in rows]


def _issue_groups(path: Path) -> list[IssueGroup]:
    """Exclusões agrupadas. Versões da Fase 1 não têm categoria nem regra: tudo era rejeição."""
    names = set(pq.read_schema(path).names)
    category = "__df_category" if "__df_category" in names else "'rejeitado'"
    rule = "__df_rule" if "__df_rule" in names else "NULL::INTEGER"
    con = sandboxed_connection(path.parent)
    try:
        rows = con.execute(
            f"SELECT {category}, __df_reason, __df_column, {rule}, count(*), min(__df_row) "  # noqa: S608
            "FROM read_parquet($path) GROUP BY ALL ORDER BY count(*) DESC, 2, 3",
            {"path": str(path)},
        ).fetchall()
    finally:
        con.close()
    return [
        IssueGroup(
            category=str(c),
            reason=str(r),
            column=col,
            rule=int(rl) if rl is not None else None,
            count=int(n),
            example_row=int(ex) if ex is not None else None,
        )
        for c, r, col, rl, n, ex in rows
    ]


def compute_quality(
    data_path: Path,
    rejected_path: Path | None,
    schema: list[dict[str, Any]],
    reconciliation: dict[str, Any],
) -> QualityResult:
    started = time.perf_counter()
    valid, columns = _profile(data_path, schema)
    issues = _issue_groups(rejected_path) if rejected_path is not None else []
    for issue in issues:
        if issue.column is None:
            continue
        for column in columns:
            if column["name"] == issue.column:
                column["issues"] += issue.count

    rejected = int(reconciliation.get("rejected", 0))
    filtered = int(reconciliation.get("filtered") or 0)
    removed = reconciliation.get("duplicates")
    names = [c["name"] for c in schema]
    remaining = duplicate_summary(data_path, names, top=0).duplicate_rows if valid else 0
    cells = valid * len(schema)
    non_null_cells = sum(c["non_null"] for c in columns)

    components: dict[str, float | None] = {
        # Dos registros que chegaram a ser avaliados para publicação, quantos passaram.
        "validity": _ratio(valid, valid + rejected),
        # Das células publicadas, quantas têm valor.
        "completeness": _ratio(non_null_cells, cells),
        # Dos registros publicados, quantos não repetem outro em todas as colunas.
        "uniqueness": (1 - remaining / valid) if valid else None,
    }
    violations = [i for i in issues if i.category != "filtrado"]
    metrics: dict[str, Any] = {
        "formula": {"version": FORMULA_VERSION, "weights": WEIGHTS},
        "components": components,
        "indicators": {
            "received": int(reconciliation.get("received", valid + rejected)),
            "valid": valid,
            "rejected": rejected,
            "filtered": filtered,
            "duplicates_removed": removed,
            "duplicates_remaining": remaining,
            "null_cells": cells - non_null_cells,
            "total_cells": cells,
            "completeness": components["completeness"],
            # Colunas às quais ao menos uma exclusão foi atribuída (nulos são medidos à parte).
            "columns_with_issues": len({i.column for i in violations if i.column is not None}),
            # Cada combinação de motivo, coluna e regra é uma regra distinta (ex.: tipo de cada coluna).
            "rules_violated": len(violations),
            "violations": sum(i.count for i in violations),
        },
        "columns": columns,
        "null_distribution": _null_distribution(data_path, schema) if valid else [],
    }
    return QualityResult(
        score=score_from(components, valid, rejected),
        metrics=metrics,
        issues=issues,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
