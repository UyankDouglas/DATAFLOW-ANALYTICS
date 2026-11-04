import datetime as dt
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.processing import pipeline
from app.processing.pipeline import data_schema, run_transform_pipeline
from app.processing.transforms import (
    RuleError,
    apply_rules,
    duplicate_exclusions,
    plan_rules,
    resolve_rules,
)
from app.processing.types import ColumnSpec, DataType

SCHEMA = [
    ColumnSpec(name="data", data_type=DataType.TEXT),
    ColumnSpec(name="vendedor", data_type=DataType.TEXT),
    ColumnSpec(name="valor", data_type=DataType.TEXT),
    ColumnSpec(name="qtd", data_type=DataType.INTEGER),
]


def frame(rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "__df_row": list(range(1, len(rows) + 1)),
            "data": [r[0] for r in rows],
            "vendedor": [r[1] for r in rows],
            "valor": [r[2] for r in rows],
            "qtd": [r[3] for r in rows],
        },
        schema={
            "__df_row": pl.Int64,
            "data": pl.String,
            "vendedor": pl.String,
            "valor": pl.String,
            "qtd": pl.Int64,
        },
    )


def run(
    rules: list[dict[str, Any]], rows: list[tuple[Any, ...]], schema: list[ColumnSpec] = SCHEMA
):
    plan = plan_rules(resolve_rules(rules), schema)
    return plan, apply_rules(frame(rows), plan)


def test_text_cleaning_rules() -> None:
    _, result = run(
        [
            {"operation": "trim", "columns": ["vendedor"]},
            {"operation": "normalize_text", "columns": ["vendedor"], "remove_accents": True},
            {"operation": "change_case", "columns": ["vendedor"], "mode": "title"},
        ],
        [("x", "  joão   da  SILVA ", "1", 1), ("x", "ÉRICA", "1", 1)],
    )
    assert result.frame["vendedor"].to_list() == ["Joao Da Silva", "Erica"]
    assert result.excluded.height == 0


def test_fix_numbers_and_standardize_dates_reject_explicitly() -> None:
    plan, result = run(
        [
            {
                "operation": "fix_numbers",
                "column": "valor",
                "target": "decimal",
                "scale": 2,
                "decimal_separator": ",",
                "thousands_separator": ".",
                "parentheses_negative": True,
            },
            {
                "operation": "standardize_dates",
                "column": "data",
                "formats": ["%d/%m/%Y", "%Y-%m-%d"],
            },
        ],
        [
            ("31/01/2025", "a", "R$ 1.234,56", 1),
            ("2025-02-01", "b", "(10,00)", 1),
            ("ontem", "c", "5,00", 1),
            ("01/03/2025", "d", "1,999", 1),
            ("01/03/2025", "e", "dez", 1),
        ],
    )
    assert plan.output[2].data_type == DataType.DECIMAL
    assert result.frame["valor"].to_list() == [Decimal("1234.56"), Decimal("-10.00")]
    assert result.frame["data"].to_list() == [dt.date(2025, 1, 31), dt.date(2025, 2, 1)]
    excluded = {r["__df_row"]: r for r in result.excluded.to_dicts()}
    assert excluded[3]["__df_reason"] == "tipo_invalido"
    assert excluded[3]["__df_rule"] == 2
    assert excluded[4]["__df_reason"] == "casas_decimais_excedidas"
    assert excluded[5]["__df_column"] == "valor"
    assert result.categories == {"rejeitado": 3}


def test_handle_nulls_fill_and_reject() -> None:
    _, filled = run(
        [
            {
                "operation": "handle_nulls",
                "columns": ["vendedor"],
                "strategy": "fill",
                "fill_value": "Sem vendedor",
            }
        ],
        [("x", None, "1", 1), ("x", "Ana", "1", None)],
    )
    assert filled.frame["vendedor"].to_list() == ["Sem vendedor", "Ana"]
    _, rejected = run(
        [{"operation": "handle_nulls", "columns": ["vendedor", "qtd"], "strategy": "reject"}],
        [("x", "Ana", "1", None), ("x", "Bia", "1", 2)],
    )
    assert rejected.frame.height == 1
    assert rejected.excluded.to_dicts()[0]["__df_column"] == "qtd"
    assert rejected.excluded.to_dicts()[0]["__df_reason"] == "valor_nulo"


def test_filter_is_counted_separately_from_rejections() -> None:
    _, result = run(
        [
            {"operation": "remove_empty_rows"},
            {
                "operation": "filter_rows",
                "match": "all",
                "conditions": [
                    {"column": "qtd", "operator": "gte", "value": "2"},
                    {
                        "column": "vendedor",
                        "operator": "in",
                        "values": ["ana", "bia"],
                        "case_insensitive": True,
                    },
                ],
            },
        ],
        [
            (None, None, None, None),
            ("x", "Ana", "1", 3),
            ("x", "Bia", "1", 1),
            ("x", "Cid", "1", 5),
            ("x", "ANA", "1", None),
        ],
    )
    assert result.frame["__df_row"].to_list() == [2]
    assert result.categories == {"rejeitado": 1, "filtrado": 3}
    filtered = [r for r in result.excluded.to_dicts() if r["__df_category"] == "filtrado"]
    assert "qtd maior ou igual a 2" in filtered[0]["__df_detail"]


def test_derived_columns_rename_and_division_by_zero() -> None:
    schema = [
        ColumnSpec(name="data", data_type=DataType.DATE, format="%Y-%m-%d"),
        ColumnSpec(name="vendedor", data_type=DataType.TEXT),
        ColumnSpec(name="valor", data_type=DataType.DECIMAL, scale=2),
        ColumnSpec(name="qtd", data_type=DataType.INTEGER),
    ]
    plan = plan_rules(
        resolve_rules(
            [
                {"operation": "derived_column", "name": "preco_unitario", "expression": {
                    "kind": "arithmetic", "operator": "divide", "left": {"column": "valor"},
                    "right": {"column": "qtd"}, "scale": 2}},
                {"operation": "derived_column", "name": "mes", "expression": {"kind": "date_part", "column": "data", "part": "year_month"}},
                {"operation": "derived_column", "name": "rotulo", "expression": {
                    "kind": "concat", "parts": [{"column": "vendedor"}, {"value": "-"}, {"column": "qtd"}], "separator": ""}},
                {"operation": "rename_columns", "mapping": {"valor": "valor_total"}},
            ]
        ),
        schema,
    )  # fmt: skip
    data = pl.DataFrame(
        {"__df_row": [1, 2], "data": [dt.date(2025, 1, 31), dt.date(2025, 2, 1)], "vendedor": ["Ana", "Bia"],
         "valor": [Decimal("10.00"), Decimal("5.00")], "qtd": [3, 0]},
        schema={"__df_row": pl.Int64, "data": pl.Date, "vendedor": pl.String, "valor": pl.Decimal(38, 2), "qtd": pl.Int64},
    )  # fmt: skip
    result = apply_rules(data, plan)
    row = result.frame.to_dicts()[0]
    assert row["preco_unitario"] == Decimal("3.33")
    assert row["mes"] == "2025-01"
    assert row["rotulo"] == "Ana-3"
    assert "valor_total" in result.frame.columns
    assert [c.name for c in plan.output][-3:] == ["preco_unitario", "mes", "rotulo"]
    assert result.excluded.to_dicts()[0]["__df_reason"] == "divisao_por_zero"


def test_convert_type_never_loses_information_silently() -> None:
    schema = [
        ColumnSpec(name="v", data_type=DataType.DECIMAL, scale=2),
        ColumnSpec(name="d", data_type=DataType.DATETIME),
    ]
    plan = plan_rules(
        resolve_rules(
            [
                {"operation": "convert_type", "column": "v", "target": "integer"},
                {"operation": "convert_type", "column": "d", "target": "date"},
            ]
        ),
        schema,
    )
    data = pl.DataFrame(
        {"__df_row": [1, 2, 3], "v": [Decimal("2.00"), Decimal("2.50"), Decimal("3.00")],
         "d": [dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 10, 0)]},
        schema={"__df_row": pl.Int64, "v": pl.Decimal(38, 2), "d": pl.Datetime("us")},
    )  # fmt: skip
    result = apply_rules(data, plan)
    assert result.frame.to_dicts() == [{"__df_row": 1, "v": 2, "d": dt.date(2025, 1, 1)}]
    assert sorted(r["__df_row"] for r in result.excluded.to_dicts()) == [2, 3]


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        ([{"operation": "trim", "columns": ["nao_existe"]}], "não existe"),
        ([{"operation": "trim", "columns": ["qtd"]}], "não é de texto"),
        (
            [{"operation": "deduplicate"}, {"operation": "trim", "columns": ["data"]}],
            "última regra",
        ),
        ([{"operation": "rename_columns", "mapping": {"data": "Vendedor"}}], "duplicado"),
        (
            [
                {
                    "operation": "filter_rows",
                    "conditions": [{"column": "vendedor", "operator": "gt", "value": "a"}],
                }
            ],
            "não se aplica",
        ),
        (
            [
                {
                    "operation": "handle_nulls",
                    "columns": ["qtd"],
                    "strategy": "fill",
                    "fill_value": "abc",
                }
            ],
            "inteiro",
        ),
        ([{"operation": "convert_type", "column": "qtd", "target": "date"}], "não é suportada"),
        (
            [
                {"operation": "rename_columns", "mapping": {"data": "data"}},
                {"operation": "trim", "columns": ["data"]},
                {
                    "operation": "derived_column",
                    "name": "x",
                    "expression": {"kind": "date_diff_days", "start": "data", "end": "data"},
                },
            ],
            "não é de data",
        ),
    ],
)
def test_plan_rejects_invalid_rules_with_position(
    rules: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(RuleError) as error:
        plan_rules(resolve_rules(rules), SCHEMA)
    assert message in error.value.message


def test_unknown_operation_and_code_like_payloads_are_refused() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        resolve_rules([{"operation": "python", "code": "__import__('os').system('id')"}])
    with pytest.raises(ValidationError):
        resolve_rules([{"operation": "trim", "columns": ["a"], "expression": "eval"}])


def _source(tmp_path: Path, rows: list[dict[str, Any]], schema: list[ColumnSpec]) -> Path:
    path = tmp_path / "source.parquet"
    table = pa.Table.from_pylist(rows, schema=data_schema(schema))
    pq.write_table(table, path)
    return path


@pytest.mark.parametrize(
    ("keep", "kept_rows", "duplicate_of"), [("first", [1, 3, 4], 1), ("last", [2, 3, 4], 2)]
)
def test_transform_pipeline_deduplicates_and_reconciles(
    tmp_path: Path, keep: str, kept_rows: list[int], duplicate_of: int
) -> None:
    schema = [
        ColumnSpec(name="vendedor", data_type=DataType.TEXT),
        ColumnSpec(name="valor", data_type=DataType.DECIMAL, scale=2),
    ]
    rows = [
        {"__df_row": 1, "vendedor": " Ana", "valor": Decimal("10.00")},
        {"__df_row": 2, "vendedor": "Ana ", "valor": Decimal("10.00")},  # duplicado após o trim
        {"__df_row": 3, "vendedor": "Bia", "valor": Decimal("10.00")},
        {"__df_row": 4, "vendedor": None, "valor": Decimal("1.00")},
        {"__df_row": 5, "vendedor": "Cid", "valor": Decimal("-1.00")},  # filtrado
    ]  # fmt: skip
    source = _source(tmp_path, rows, schema)
    plan = plan_rules(
        resolve_rules(
            [
                {"operation": "trim", "columns": ["vendedor"]},
                {
                    "operation": "filter_rows",
                    "conditions": [{"column": "valor", "operator": "gte", "value": "0"}],
                },
                {"operation": "deduplicate", "columns": ["vendedor", "valor"], "keep": keep},
            ]
        ),
        schema,
    )
    result = run_transform_pipeline(
        source,
        tmp_path / "out",
        schema,
        plan,
        batch_rows=2,
        rows_total=5,
        on_progress=lambda _: None,
    )
    assert result.reconciliation == {
        "received": 5, "valid": 3, "rejected": 0, "filtered": 1, "duplicates": 1,
        "duplicates_policy": "removidos_dos_validos", "consistent": True,
    }  # fmt: skip
    data = pq.read_table(result.data_path).to_pylist()
    assert [r["__df_row"] for r in data] == kept_rows
    excluded = {r["__df_category"]: r for r in pq.read_table(result.rejected_path).to_pylist()}
    assert excluded["duplicado"]["__df_duplicate_of"] == duplicate_of
    assert excluded["duplicado"]["__df_rule"] == 3
    assert excluded["filtrado"]["vendedor"] == "Cid"
    assert excluded["filtrado"]["valor"] == "-1.00"  # valor de entrada preservado como texto
    # Ambos os " Ana"/"Ana " viram "Ana": o registro removido guarda o valor original.
    assert excluded["duplicado"]["vendedor"] in (" Ana", "Ana ")


def _previous_deduplicate(
    outputs: Any,
    target: Path,
    plan: Any,
    source: Path,
    input_schema: list[ColumnSpec],
    result: Any,
    batch_rows: int,
) -> int:
    """A implementação anterior, com tudo em memória, como referência de resultado (ADR-031)."""
    outputs.close()  # ela relia e regravava o arquivo de exclusões inteiro
    keys = plan.dedup_keys
    keep_first = plan.dedup.rule.keep == "first"
    distinct = (
        pl.struct(keys).is_first_distinct() if keep_first else pl.struct(keys).is_last_distinct()
    )
    kept_row = pl.col("__df_row").first() if keep_first else pl.col("__df_row").last()
    marked = (
        pl.scan_parquet(outputs.data_path)
        .with_columns(distinct.alias("__df_keep"), kept_row.over(keys).alias("__df_kept_row"))
        .collect()
    )
    kept = marked.filter(pl.col("__df_keep")).drop("__df_keep", "__df_kept_row")
    pq.write_table(kept.to_arrow().cast(outputs.valid_schema), target, compression="zstd")
    duplicates = marked.filter(~pl.col("__df_keep")).select("__df_row", "__df_kept_row")
    if not duplicates.height:
        return 0
    originals = (
        pl.scan_parquet(source)
        .select(["__df_row", *[s.name for s in input_schema]])
        .join(duplicates.lazy().select("__df_row"), on="__df_row", how="semi")
        .collect()
    )
    existing = pq.read_table(outputs.rejected_path) if outputs.rejected_path.exists() else None
    excluded = duplicate_exclusions(duplicates, plan)
    rows = pipeline._with_input_values(excluded, originals, input_schema).sort("__df_row")
    table = rows.to_arrow().cast(outputs.rejected_schema)
    pq.write_table(
        pa.concat_tables([existing, table]) if existing is not None else table,
        outputs.rejected_path,
        compression="zstd",
    )
    pipeline._collect_samples(result, rows)
    return duplicates.height


def _varied_rows(count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    names = ["Ana", " Ana", "Ana ", "Bia", "Cid", "Davi", None]
    rows = []
    for row in range(1, count + 1):
        rows.append(
            {
                "__df_row": row,
                "data": rng.choice([None, *(dt.date(2025, 1, d) for d in range(1, 6))]),
                "vendedor": rng.choice(names),
                "valor": Decimal(rng.randint(-3, 12)).quantize(Decimal("0.01")),
                "qtd": rng.choice([0, 1, 2, 3, None]),
                "ativo": rng.choice([True, False, None]),
            }
        )
    return rows


@pytest.mark.parametrize("keep", ["first", "last"])
@pytest.mark.parametrize(
    "keys",
    [
        ["vendedor"],  # poucas chaves, muitos duplicados, nulos entre eles
        ["data", "vendedor"],
        ["preco_unitario", "ativo"],  # coluna derivada e booleano na chave
        [],  # todas as colunas: quase nenhum duplicado
    ],
)
@pytest.mark.parametrize("batch_rows", [7, 10_000])
def test_deduplication_matches_previous_in_memory_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    keep: str,
    keys: list[str],
    batch_rows: int,
) -> None:
    schema = [
        ColumnSpec(name="data", data_type=DataType.DATE, format="%Y-%m-%d"),
        ColumnSpec(name="vendedor", data_type=DataType.TEXT),
        ColumnSpec(name="valor", data_type=DataType.DECIMAL, scale=2),
        ColumnSpec(name="qtd", data_type=DataType.INTEGER),
        ColumnSpec(name="ativo", data_type=DataType.BOOLEAN),
    ]
    source = _source(tmp_path, _varied_rows(600, seed=len(keys) * 10 + batch_rows), schema)
    rules = [
        {"operation": "trim", "columns": ["vendedor"]},
        {"operation": "derived_column", "name": "preco_unitario", "expression": {
            "kind": "arithmetic", "operator": "divide", "left": {"column": "valor"},
            "right": {"column": "qtd"}, "scale": 2}},  # qtd 0: rejeitado na 1ª passada
        {"operation": "filter_rows",
         "conditions": [{"column": "valor", "operator": "gte", "value": "0"}]},
        {"operation": "deduplicate", "columns": keys, "keep": keep},
    ]  # fmt: skip
    plan = plan_rules(resolve_rules(rules), schema)

    def execute(out: Path) -> Any:
        return run_transform_pipeline(
            source, out, schema, plan,
            batch_rows=batch_rows, rows_total=600, on_progress=lambda _: None,
        )  # fmt: skip

    current = execute(tmp_path / "atual")
    monkeypatch.setattr(pipeline, "_deduplicate", _previous_deduplicate)
    previous = execute(tmp_path / "anterior")

    assert current.rows_duplicates == previous.rows_duplicates
    assert current.rows_duplicates
    assert current.reconciliation == previous.reconciliation
    assert current.reconciliation["consistent"]
    assert current.reasons == previous.reasons
    assert current.samples == previous.samples
    assert current.null_counts == previous.null_counts
    assert pq.read_table(current.data_path).to_pylist() == (
        pq.read_table(previous.data_path).to_pylist()
    )
    assert pq.read_table(current.rejected_path).to_pylist() == (
        pq.read_table(previous.rejected_path).to_pylist()
    )
