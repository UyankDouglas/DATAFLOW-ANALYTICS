"""Fórmula da nota de qualidade e cálculo do relatório sobre arquivos Parquet reais."""

from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.analytics.quality import WEIGHTS, compute_quality, score_from

SCHEMA = [
    {"name": "cliente", "data_type": "text"},
    {"name": "valor", "data_type": "integer"},
]


def _write(path: Path, rows: list[tuple[str | None, int | None]]) -> Path:
    frame = pl.DataFrame(
        {
            "__df_row": list(range(1, len(rows) + 1)),
            "cliente": [r[0] for r in rows],
            "valor": [r[1] for r in rows],
        },
        schema={"__df_row": pl.Int64, "cliente": pl.String, "valor": pl.Int64},
    )
    frame.write_parquet(path)
    return path


def _rejected(path: Path, rows: list[dict[str, object]], phase1: bool = False) -> Path:
    fields = [
        ("__df_row", pa.int64()),
        ("__df_line", pa.int64()),
        ("__df_reason", pa.string()),
        ("__df_column", pa.string()),
        ("__df_detail", pa.string()),
    ]
    if not phase1:
        fields += [
            ("__df_category", pa.string()),
            ("__df_rule", pa.int32()),
            ("__df_duplicate_of", pa.int64()),
        ]
    fields += [("cliente", pa.string()), ("valor", pa.string())]
    schema = pa.schema(fields)
    columns = {name: [r.get(name) for r in rows] for name, _ in fields}
    pq.write_table(pa.table(columns, schema=schema), path)
    return path


def test_score_formula_is_the_documented_weighted_average() -> None:
    assert WEIGHTS == {"validity": 0.4, "completeness": 0.4, "uniqueness": 0.2}
    components = {"validity": 0.9, "completeness": 0.5, "uniqueness": 1.0}
    assert score_from(components, valid=9, rejected=1) == pytest.approx(76.0)
    assert score_from(components, valid=0, rejected=0) is None  # nada a avaliar
    assert score_from(components, valid=0, rejected=5) == 0.0  # tudo rejeitado


def test_report_counts_validity_completeness_uniqueness_and_issues(tmp_path: Path) -> None:
    data = _write(
        tmp_path / "data.parquet",
        [("Ana", 10), ("Ana", 10), ("Bia", None), (None, 5)],
    )
    rejected = _rejected(
        tmp_path / "rejected.parquet",
        [
            {"__df_row": 5, "__df_reason": "tipo_invalido", "__df_column": "valor",
             "__df_category": "rejeitado", "valor": "dez"},
            {"__df_row": 6, "__df_reason": "removido_por_filtro", "__df_category": "filtrado",
             "__df_rule": 1, "cliente": "Cid"},
            {"__df_row": 7, "__df_reason": "registro_duplicado", "__df_category": "duplicado",
             "__df_rule": 2, "__df_duplicate_of": 1, "cliente": "Ana", "valor": "10"},
        ],
    )  # fmt: skip
    reconciliation = {"received": 7, "valid": 4, "rejected": 1, "filtered": 1, "duplicates": 1}

    result = compute_quality(data, rejected, SCHEMA, reconciliation)

    components = result.metrics["components"]
    assert components["validity"] == pytest.approx(4 / 5)  # filtrados e removidos não contam
    assert components["completeness"] == pytest.approx(6 / 8)
    assert components["uniqueness"] == pytest.approx(3 / 4)  # Ana/10 repete na versão
    expected = 100 * (0.4 * 0.8 + 0.4 * 0.75 + 0.2 * 0.75)
    assert result.score == pytest.approx(round(expected, 1))

    indicators = result.metrics["indicators"]
    assert indicators["null_cells"] == 2
    assert indicators["duplicates_removed"] == 1
    assert indicators["duplicates_remaining"] == 1
    assert indicators["columns_with_issues"] == 1  # só "valor" tem exclusão atribuída
    assert indicators["rules_violated"] == 2  # tipo em valor + duplicidade (filtro não é violação)
    assert indicators["violations"] == 2
    by_name = {c["name"]: c for c in result.metrics["columns"]}
    assert (by_name["valor"]["nulls"], by_name["valor"]["min"], by_name["valor"]["max"]) == (
        1,
        5,
        10,
    )
    assert by_name["valor"]["issues"] == 1
    assert by_name["cliente"]["distinct"] == 2
    assert result.metrics["null_distribution"] == [{"nulls": 0, "rows": 2}, {"nulls": 1, "rows": 2}]
    assert {(i.category, i.reason, i.rule) for i in result.issues} == {
        ("rejeitado", "tipo_invalido", None),
        ("filtrado", "removido_por_filtro", 1),
        ("duplicado", "registro_duplicado", 2),
    }


def test_phase1_rejected_files_without_category_are_read_as_rejections(tmp_path: Path) -> None:
    data = _write(tmp_path / "data.parquet", [("Ana", 1)])
    rejected = _rejected(
        tmp_path / "rejected.parquet",
        [{"__df_row": 2, "__df_reason": "linha_vazia"}],
        phase1=True,
    )
    result = compute_quality(
        data, rejected, SCHEMA, {"received": 2, "valid": 1, "rejected": 1, "duplicates": None}
    )
    assert [(i.category, i.reason, i.rule) for i in result.issues] == [
        ("rejeitado", "linha_vazia", None)
    ]
    assert result.metrics["indicators"]["filtered"] == 0


def test_version_without_valid_rows_scores_zero(tmp_path: Path) -> None:
    data = _write(tmp_path / "data.parquet", [])
    result = compute_quality(
        data, None, SCHEMA, {"received": 3, "valid": 0, "rejected": 3, "duplicates": None}
    )
    assert result.score == 0.0
    assert result.metrics["components"]["completeness"] is None
    assert result.metrics["null_distribution"] == []
