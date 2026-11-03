"""Benchmark reproduzível da Fase 2: importação de XLSX e transformação com deduplicação.

Mede as mesmas funções executadas pelo worker, sem banco nem armazenamento:
1. inspeção do contêiner e prévia da aba "Vendas" (planilha gerada pelo script de amostras);
2. importação da aba inteira para Parquet;
3. transformação dessa versão (espaços, filtro, coluna derivada e deduplicação);
4. análise de duplicidades com DuckDB sobre a mesma versão, conferida contra o pipeline.

    uv run python -m app.scripts.benchmark_etl ../samples/generated/vendas_atendimentos_100000.xlsx
"""

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import openpyxl
import polars as pl

from app.analytics.query import duplicate_summary
from app.processing.inference import infer_columns
from app.processing.pipeline import run_transform_pipeline, run_xlsx_pipeline
from app.processing.transforms import plan_rules, resolve_rules
from app.processing.types import ColumnConfig, ParseOptions
from app.processing.xlsx import XlsxLimits, inspect_xlsx, parse_xlsx_sample

LIMITS = XlsxLimits(max_uncompressed_bytes=400 * 1024 * 1024, max_entries=2000, max_ratio=200)
TEXT_COLUMNS = ["vendedor", "equipe", "produto", "categoria", "status", "canal"]
RULES: list[dict[str, Any]] = [
    {"operation": "trim", "columns": TEXT_COLUMNS},
    {
        "operation": "filter_rows",
        "conditions": [{"column": "status", "operator": "ne", "value": "cancelado"}],
    },
    {
        "operation": "derived_column",
        "name": "valor_unitario",
        "expression": {
            "kind": "arithmetic",
            "operator": "divide",
            "left": {"column": "valor"},
            "right": {"column": "quantidade"},
            "scale": 2,
        },
    },
    {"operation": "deduplicate", "columns": ["vendedor", "produto"], "keep": "first"},
]


def run(path: Path, batch_rows: int) -> dict[str, object]:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    info = inspect_xlsx(path, LIMITS)
    timings["inspecao_upload_s"] = time.perf_counter() - t0

    options = ParseOptions(sheet="Vendas")
    t1 = time.perf_counter()
    sample = parse_xlsx_sample(path, options, max_rows=1000)
    options = options.model_copy(update={"header_row": sample.layout.header_row})
    inferred = infer_columns(sample.table.header, sample.table.rows, options)
    columns = [
        ColumnConfig(
            position=i.position,
            source_name=i.source_name,
            name=i.source_name,
            data_type=i.inferred_type,
            format=i.format,
            scale=i.scale,
        )
        for i in inferred
    ]
    timings["preview_inferencia_s"] = time.perf_counter() - t1

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        t2 = time.perf_counter()
        imported = run_xlsx_pipeline(
            path,
            work / "v1",
            options,
            columns,
            sample.table.header,
            first_column=sample.layout.first_column,
            batch_rows=batch_rows,
            on_progress=lambda _: None,
        )
        timings["importacao_xlsx_s"] = time.perf_counter() - t2
        assert imported.data_path is not None

        plan = plan_rules(resolve_rules(RULES), imported.output_schema)
        t3 = time.perf_counter()
        transformed = run_transform_pipeline(
            imported.data_path,
            work / "v2",
            imported.output_schema,
            plan,
            batch_rows=batch_rows,
            rows_total=imported.rows_valid,
            on_progress=lambda _: None,
        )
        timings["transformacao_s"] = time.perf_counter() - t3
        for key, value in transformed.timings_ms.items():
            timings[f"transformacao_{key}_s"] = value / 1000

        # Mesma chave, sem as regras anteriores: DuckDB (análise) x Polars (job) devem bater.
        only_dedup = plan_rules(resolve_rules(RULES[-1:]), imported.output_schema)
        deduplicated = run_transform_pipeline(
            imported.data_path,
            work / "v2b",
            imported.output_schema,
            only_dedup,
            batch_rows=batch_rows,
            rows_total=imported.rows_valid,
            on_progress=lambda _: None,
        )
        t4 = time.perf_counter()
        summary = duplicate_summary(imported.data_path, ["vendedor", "produto"])
        timings["analise_duplicidades_duckdb_s"] = time.perf_counter() - t4

    return {
        "arquivo": path.name,
        "tamanho_mb": round(path.stat().st_size / 1024 / 1024, 2),
        "abas": [s["name"] for s in info["sheets"]],
        "linha_cabecalho_detectada": sample.layout.header_row,
        "importacao": imported.reconciliation,
        "transformacao": transformed.reconciliation,
        "duplicidades_duckdb_vs_pipeline": {
            "duckdb": summary.duplicate_rows,
            "pipeline": deduplicated.rows_duplicates,
            "iguais": summary.duplicate_rows == deduplicated.rows_duplicates,
        },
        "tempos_s": {k: round(v, 3) for k, v in timings.items()},
        "registros_por_segundo": {
            "importacao_xlsx": round(imported.rows_total / timings["importacao_xlsx_s"]),
            "transformacao": round(transformed.rows_total / timings["transformacao_s"]),
        },
        "ambiente": {
            "python": platform.python_version(),
            "sistema": f"{platform.system()} {platform.release()}",
            "cpu": platform.processor() or platform.machine(),
            "polars": pl.__version__,
            "duckdb": duckdb.__version__,
            "openpyxl": openpyxl.__version__,
            "lote": batch_rows,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--batch-rows", type=int, default=50_000)
    args = parser.parse_args()
    for file in args.files:
        print(json.dumps(run(file, args.batch_rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
