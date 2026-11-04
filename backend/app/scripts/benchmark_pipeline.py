"""Benchmark reproduzível do pipeline (sem banco nem armazenamento).

Mede as mesmas etapas executadas pelo worker: inspeção do arquivo, leitura/validação,
conversão de tipos, escrita Parquet e uma consulta paginada com DuckDB. Também mede o relatório
de qualidade, uma consulta do explorer e as consultas analíticas dos dashboards (KPIs,
agrupamento por categoria, série mensal e comparação entre períodos) e as exportações completas da
versão em CSV e XLSX, com o mesmo leitor e os mesmos escritores do worker, até os limites de
registros que a API aceita (`EXPORT_MAX_ROWS` e `EXPORT_XLSX_MAX_ROWS`).

    uv run python -m app.scripts.benchmark_pipeline ../samples/generated/vendas_100000.csv
"""

import argparse
import datetime as dt
import json
import platform
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Iterator
from pathlib import Path

import duckdb
import polars as pl

from app.analytics.aggregate import AggregateResult, AggregateSpec, plan_aggregate, run_aggregate
from app.analytics.quality import compute_quality
from app.analytics.query import (
    build_where,
    count_rows,
    fetch_page,
    quote_identifier,
    sandboxed_connection,
)
from app.core.config import get_settings
from app.processing.export_writers import ExportColumn, write_csv, write_xlsx
from app.processing.inference import infer_columns
from app.processing.inspection import StreamInspector, parse_sample
from app.processing.pipeline import PipelineResult, run_csv_pipeline, specs_from_columns
from app.processing.transforms import Condition
from app.processing.types import ColumnConfig, ParseOptions


def _peak_rss_mb() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor, 1)


def _bi_timings(data_path: Path, columns: list[ColumnConfig]) -> dict[str, float]:
    specs = specs_from_columns(columns)
    by_type = {
        t: next((c.name for c in columns if c.data_type.value == t), None)
        for t in ("integer", "decimal", "text", "date", "datetime")
    }
    measure = by_type["decimal"] or by_type["integer"]
    category = by_type["text"]
    moment = by_type["date"] or by_type["datetime"]
    value = {"aggregation": "sum", "column": measure} if measure else {"aggregation": "count"}

    def timed(spec: dict[str, object]) -> tuple[float, AggregateResult]:
        plan = plan_aggregate(AggregateSpec.model_validate(spec), specs)
        start = time.perf_counter()
        outcome = run_aggregate(data_path, plan)
        return time.perf_counter() - start, outcome

    timings: dict[str, float] = {}
    kpis = [{"aggregation": "count"}]
    if measure:
        kpis += [{"aggregation": a, "column": measure} for a in ("sum", "avg", "min", "max")]
    if category:
        kpis.append({"aggregation": "count_distinct", "column": category})
    timings["bi_kpis_s"], _ = timed({"metrics": kpis})
    if category:
        timings["bi_por_categoria_com_outros_s"], _ = timed(
            {"metrics": [value], "dimension": {"column": category}, "limit": 10}
        )
    if moment:
        timings["bi_serie_mensal_s"], _ = timed(
            {"metrics": [value], "dimension": {"column": moment, "granularity": "month"}}
        )
        _, bounds = timed({"metrics": [{"aggregation": "max", "column": moment}]})
        last = str(bounds.rows[0].values[0])[:10]
        end = dt.date.fromisoformat(last)
        comparison = {
            "column": moment,
            "start": (end - dt.timedelta(days=29)).isoformat(),
            "end": end.isoformat(),
        }
        timings["bi_comparacao_periodos_s"], _ = timed(
            {"metrics": [value], "comparison": comparison}
        )
        if category:
            timings["bi_comparacao_por_categoria_s"], _ = timed(
                {
                    "metrics": [value],
                    "dimension": {"column": category},
                    "limit": 8,
                    "comparison": comparison,
                }
            )
    return timings


def _export_timings(
    data_path: Path, columns: list[ColumnConfig], work: Path
) -> tuple[dict[str, float], dict[str, int]]:
    """Exporta como o worker, até o limite de registros que a API aceita para cada formato."""
    settings = get_settings()
    names = [c.name for c in columns]
    export_columns = [ExportColumn(c.name, c.data_type, c.scale) for c in columns]
    exported: dict[str, int] = {}

    def rows(limit: int, fmt: str) -> Iterator[tuple[object, ...]]:
        con = sandboxed_connection(data_path.parent)
        try:
            cursor = con.execute(
                f"SELECT {', '.join(quote_identifier(n) for n in names)} "  # noqa: S608
                "FROM read_parquet($path) ORDER BY __df_row LIMIT $limit",
                {"path": str(data_path), "limit": limit},
            )
            while batch := cursor.fetchmany(5_000):
                exported[fmt] = exported.get(fmt, 0) + len(batch)
                yield from batch
        finally:
            con.close()

    timings: dict[str, float] = {}
    start = time.perf_counter()
    write_csv(
        work / "exportacao.csv",
        export_columns,
        rows(settings.export_max_rows, "csv"),
        "excel_br",
    )
    timings["exportacao_csv_s"] = time.perf_counter() - start
    start = time.perf_counter()
    write_xlsx(
        work / "exportacao.xlsx",
        export_columns,
        rows(settings.export_xlsx_max_rows, "xlsx"),
        "dados",
    )
    timings["exportacao_xlsx_s"] = time.perf_counter() - start
    return timings, exported


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

        # Fase 3: relatório de qualidade e consulta do explorer com filtro + busca + contagem.
        t4 = time.perf_counter()
        schema = [{"name": c.name, "data_type": c.data_type.value} for c in columns]
        quality = compute_quality(
            result.data_path, result.rejected_path, schema, result.reconciliation
        )
        timings["relatorio_qualidade_s"] = time.perf_counter() - t4
        specs = specs_from_columns(columns)
        text = next((c.name for c in columns if c.data_type.value == "text"), None)
        conditions = [Condition(column=names[0], operator="not_null")]
        where = build_where(conditions, "all", "a" if text else None, specs)
        t5 = time.perf_counter()
        fetch_page(
            result.data_path,
            names,
            columns=None,
            sort=names[-1],
            direction="desc",
            limit=50,
            offset=0,
            where=where,
        )
        filtered = count_rows(result.data_path, where)
        timings["consulta_filtrada_com_contagem_s"] = time.perf_counter() - t5

        # Fase 4: consultas dos dashboards, com as colunas que o usuário escolheria.
        bi = _bi_timings(result.data_path, columns)
        timings.update(bi)
        # Fase 5: exportação como o worker faz (leitura em lotes + escrita), até os limites.
        export_timings, exported = _export_timings(result.data_path, columns, Path(tmp))
        timings.update(export_timings)
        parquet_mb = result.data_path.stat().st_size / 1024 / 1024

    return {
        "arquivo": path.name,
        "tamanho_mb": round(path.stat().st_size / 1024 / 1024, 2),
        "registros": result.rows_total,
        "validos": result.rows_valid,
        "rejeitados": result.rows_rejected,
        "motivos": dict(result.reasons),
        "parquet_mb": round(parquet_mb, 2),
        "nota_qualidade": quality.score,
        "registros_filtrados": filtered,
        "registros_exportados": exported,
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
