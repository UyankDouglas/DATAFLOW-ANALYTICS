"""Benchmark reproduzível do pipeline (sem banco nem armazenamento).

Mede as mesmas etapas executadas pelo worker: inspeção do arquivo, leitura/validação,
conversão de tipos, escrita Parquet e uma consulta paginada com DuckDB.

    uv run python -m app.scripts.benchmark_pipeline ../samples/generated/vendas_100000.csv
"""

import argparse
import json
import platform
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import duckdb
import polars as pl

from app.analytics.query import fetch_page
from app.processing.inference import infer_columns
from app.processing.inspection import StreamInspector, parse_sample
from app.processing.pipeline import PipelineResult, run_csv_pipeline
from app.processing.types import ColumnConfig, ParseOptions


def _peak_rss_mb() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor, 1)


def run(path: Path, batch_rows: int) -> dict[str, object]:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    inspector = StreamInspector()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            inspector.feed(chunk)
    detection = inspector.finish()
    timings["inspecao_upload_s"] = time.perf_counter() - t0

    options = ParseOptions(
        encoding=detection["suggested_encoding"],
        delimiter=detection["delimiter"],
        decimal_separator=detection["decimal_separator"],
        thousands_separator=detection["thousands_separator"],
    )
    t1 = time.perf_counter()
    sample = parse_sample(
        path.read_bytes()[: 2 * 1024 * 1024], options, truncated=True, max_rows=1000
    )
    inferred = infer_columns(sample.header, sample.rows, options)
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

    def execute(out: Path) -> PipelineResult:
        return run_csv_pipeline(
            path,
            out,
            options,
            columns,
            sample.header,
            batch_rows=batch_rows,
            max_field_bytes=1024 * 1024,
            on_progress=lambda _: None,
        )

    # Execução separada para memória: o tracemalloc distorce os tempos.
    with tempfile.TemporaryDirectory() as tmp:
        tracemalloc.start()
        execute(Path(tmp))
        _, python_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    with tempfile.TemporaryDirectory() as tmp:
        t2 = time.perf_counter()
        result = execute(Path(tmp))
        timings["pipeline_total_s"] = time.perf_counter() - t2
        for key, value in result.timings_ms.items():
            timings[f"pipeline_{key}_s"] = value / 1000

        assert result.data_path is not None
        names = [c.name for c in columns]
        t3 = time.perf_counter()
        fetch_page(
            result.data_path,
            names,
            columns=None,
            sort=names[-1],
            direction="desc",
            limit=50,
            offset=5000,
        )
        timings["consulta_pagina_ordenada_s"] = time.perf_counter() - t3
        parquet_mb = result.data_path.stat().st_size / 1024 / 1024

    return {
        "arquivo": path.name,
        "tamanho_mb": round(path.stat().st_size / 1024 / 1024, 2),
        "registros": result.rows_total,
        "validos": result.rows_valid,
        "rejeitados": result.rows_rejected,
        "motivos": dict(result.reasons),
        "parquet_mb": round(parquet_mb, 2),
        "tempos_s": {k: round(v, 3) for k, v in timings.items()},
        "registros_por_segundo": round(result.rows_total / timings["pipeline_total_s"]),
        "memoria_pico_python_mb": round(python_peak / 1024 / 1024, 1),
        "memoria_pico_processo_mb": _peak_rss_mb(),
        "ambiente": {
            "python": platform.python_version(),
            "sistema": f"{platform.system()} {platform.release()}",
            "cpu": platform.processor() or platform.machine(),
            "polars": pl.__version__,
            "duckdb": duckdb.__version__,
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
