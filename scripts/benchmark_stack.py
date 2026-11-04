"""Benchmark do fluxo completo contra uma instalação em execução (Docker Compose).

Usa só a API pública e a biblioteca padrão do Python, como um cliente qualquer: cadastra uma conta
descartável, envia os arquivos em streaming, processa, consulta, transforma e exporta, e confere
as contagens em cada etapa (falha com código 1 se algo não bater). Os tempos do servidor vêm das
métricas que o worker grava em cada job; os de ponta a ponta são medidos aqui.

    python3 scripts/generate_samples.py --rows 1000000 500000 100000 --only vendas
    uv run --project backend python scripts/generate_samples.py --xlsx --rows 280000
    python3 scripts/benchmark_stack.py --base-url http://localhost:8080 \\
        --large samples/generated/vendas_1000000.csv \\
        --csv-limit samples/generated/vendas_500000.csv \\
        --xlsx-limit samples/generated/vendas_100000.csv \\
        --workbook samples/generated/vendas_atendimentos_280000.xlsx \\
        --out benchmark-stack.json

Imprime a linha `BENCHMARK_STACK {json}` e, na CI, um resumo em `$GITHUB_STEP_SUMMARY`.
"""

import argparse
import http.client
import json
import os
import secrets
import ssl
import sys
import time
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

TERMINAL = {"succeeded", "failed", "cancelled", "expired"}


class Failure(Exception):
    pass


class Client:
    def __init__(self, base_url: str, insecure: bool) -> None:
        parts = urlsplit(base_url)
        self.https = parts.scheme == "https"
        self.host = parts.hostname or "localhost"
        self.port = parts.port or (443 if self.https else 80)
        self.context = ssl._create_unverified_context() if insecure else None  # noqa: S323
        self.cookies: dict[str, str] = {}

    def _connection(self, timeout: float) -> http.client.HTTPConnection:
        if self.https:
            return http.client.HTTPSConnection(
                self.host, self.port, timeout=timeout, context=self.context
            )
        return http.client.HTTPConnection(self.host, self.port, timeout=timeout)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        payload: Any = None,
        headers: dict[str, str] | None = None,
        expect: tuple[int, ...] = (200, 201, 202),
        timeout: float = 120,
        sink: Path | None = None,
    ) -> tuple[int, Any, float]:
        """Faz a requisição e devolve (status, JSON ou bytes, milissegundos)."""
        all_headers = {"Accept": "application/json", **(headers or {})}
        if payload is not None:
            body = json.dumps(payload).encode()
            all_headers["Content-Type"] = "application/json"
        if method not in ("GET", "HEAD") and "df_csrf" in self.cookies:
            all_headers["X-CSRF-Token"] = self.cookies["df_csrf"]
        if self.cookies:
            all_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        conn = self._connection(timeout)
        started = time.perf_counter()
        try:
            conn.request(method, path, body=body, headers=all_headers)
            response = conn.getresponse()
            for header in response.headers.get_all("Set-Cookie") or []:
                jar: SimpleCookie = SimpleCookie()
                jar.load(header)
                for key, morsel in jar.items():
                    self.cookies[key] = morsel.value
            if sink is not None and response.status in expect:
                with sink.open("wb") as handle:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
                data: Any = None
            else:
                raw = response.read()
                kind = response.headers.get("Content-Type", "")
                data = json.loads(raw) if kind.startswith("application/json") and raw else raw
        finally:
            conn.close()
        elapsed = (time.perf_counter() - started) * 1000
        if response.status not in expect:
            raise Failure(f"{method} {path} → {response.status}: {str(data)[:400]}")
        return response.status, data, elapsed


# ---------------------------------------------------------------- etapas


def register(client: Client) -> None:
    client.request("GET", "/api/v1/auth/csrf")
    suffix = uuid.uuid4().hex[:10]
    client.request(
        "POST",
        "/api/v1/auth/register",
        payload={
            "full_name": "Benchmark CI",
            "email": f"benchmark-{suffix}@example.com",
            # Conta descartável desta execução; a senha não é guardada em lugar nenhum.
            "password": f"Bm-{secrets.token_urlsafe(18)}",
            "workspace_name": f"Benchmark {suffix[:4]}",
        },
        expect=(201,),
    )


def upload(client: Client, path: Path, name: str | None = None) -> tuple[str, float]:
    size = path.stat().st_size
    query = f"?dataset_name={quote(name)}" if name else ""
    with path.open("rb") as handle:
        _, data, ms = client.request(
            "POST",
            f"/api/v1/datasets/upload{query}",
            body=handle,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(size),
                "X-File-Name": quote(path.name),
            },
            expect=(201,),
            timeout=600,
        )
    return data["dataset"]["id"], ms


def wait(client: Client, path: str, timeout: float) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    while True:
        _, item, _ = client.request("GET", path)
        if item["status"] in TERMINAL:
            return item, (time.perf_counter() - started) * 1000
        if time.perf_counter() - started > timeout:
            raise Failure(f"{path} não terminou em {timeout:.0f} s (status {item['status']})")
        time.sleep(0.5)


def import_dataset(client: Client, dataset_id: str, timeout: float = 900) -> dict[str, Any]:
    _, preview, preview_ms = client.request("GET", f"/api/v1/datasets/{dataset_id}/preview")
    columns = [
        {
            "position": c["position"],
            "source_name": c["source_name"],
            "name": c["source_name"],
            "data_type": c["inferred_type"],
            "format": c["format"],
            "scale": c["scale"],
        }
        for c in preview["columns"]
    ]
    _, job, _ = client.request(
        "POST",
        f"/api/v1/datasets/{dataset_id}/imports",
        payload={"parse_options": preview["parse_options"], "columns": columns},
        expect=(202,),
    )
    finished, wall_ms = wait(client, f"/api/v1/jobs/{job['id']}", timeout)
    if finished["status"] != "succeeded":
        raise Failure(f"importação {job['id']} terminou como {finished['status']}")
    return {"job": finished, "wall_ms": round(wall_ms), "preview_ms": round(preview_ms)}


def job_summary(job: dict[str, Any]) -> dict[str, Any]:
    metrics = job.get("metrics") or {}
    return {
        "rows_total": job["rows_total"],
        "rows_valid": job["rows_valid"],
        "rows_rejected": job["rows_rejected"],
        "rows_duplicates": job.get("rows_duplicates"),
        "timings_ms": metrics.get("timings_ms"),
        "rows_per_second": metrics.get("rows_per_second"),
        "peak_memory_mb": metrics.get("peak_memory_mb"),
        "start_memory_mb": metrics.get("start_memory_mb"),
    }


def queries(client: Client, dataset_id: str, rows: int) -> dict[str, float]:
    last_page = max(rows // 50, 1)
    rows_path = (
        f"/api/v1/datasets/{dataset_id}/rows?page={last_page}&page_size=50"
        "&sort=valor&direction=desc"
    )
    timings: dict[str, float] = {}
    _, body, timings["pagina_final_cache_vazio_ms"] = client.request("GET", rows_path)
    if body["total"] != rows:
        raise Failure(f"consulta devolveu total {body['total']}, esperado {rows}")
    _, _, timings["pagina_final_com_cache_ms"] = client.request("GET", rows_path)
    _, found, timings["explorer_busca_filtro_contagem_ms"] = client.request(
        "POST",
        f"/api/v1/datasets/{dataset_id}/rows/query",
        payload={
            "search": "a",
            "filters": [{"column": "status", "operator": "eq", "value": "pago"}],
            "sort": "valor",
            "direction": "desc",
        },
    )
    if not 0 < found["total"] < rows:
        raise Failure(f"filtro do explorer devolveu {found['total']}")
    analytics = f"/api/v1/datasets/{dataset_id}/analytics"
    specs = {
        "kpis_ms": {
            "metrics": [
                {"aggregation": "count"},
                {"aggregation": "sum", "column": "valor"},
                {"aggregation": "avg", "column": "valor"},
                {"aggregation": "count_distinct", "column": "vendedor"},
            ]
        },
        "por_vendedor_com_outros_ms": {
            "metrics": [{"aggregation": "sum", "column": "valor"}],
            "dimension": {"column": "vendedor"},
            "limit": 10,
        },
        "serie_mensal_ms": {
            "metrics": [{"aggregation": "sum", "column": "valor"}],
            "dimension": {"column": "data_venda", "granularity": "month"},
        },
    }
    for name, spec in specs.items():
        _, result, timings[name] = client.request("POST", analytics, payload=spec)
        if name == "kpis_ms" and int(result["rows"][0]["values"][0]) != rows:
            raise Failure(f"KPI de contagem devolveu {result['rows'][0]['values'][0]}")
    return {k: round(v) for k, v in timings.items()}


def deduplicate(client: Client, dataset_id: str, rows: int) -> dict[str, Any]:
    _, detail, _ = client.request("GET", f"/api/v1/datasets/{dataset_id}")
    _, tset, _ = client.request(
        "POST",
        f"/api/v1/datasets/{dataset_id}/transformation-sets",
        payload={
            "name": "Benchmark",
            "rules": [
                {"operation": "trim", "columns": ["vendedor", "produto"]},
                {"operation": "deduplicate", "columns": ["vendedor", "produto"], "keep": "first"},
            ],
        },
        expect=(201,),
    )
    _, job, _ = client.request(
        "POST",
        f"/api/v1/datasets/{dataset_id}/transform-jobs",
        payload={
            "source_version_id": detail["current_version_id"],
            "transformation_set_id": tset["id"],
        },
        expect=(202,),
    )
    finished, wall_ms = wait(client, f"/api/v1/jobs/{job['id']}", 900)
    if finished["status"] != "succeeded":
        raise Failure(f"transformação terminou como {finished['status']}")
    summary = job_summary(finished)
    if summary["rows_total"] != rows or (
        summary["rows_valid"] + (summary["rows_duplicates"] or 0) + summary["rows_rejected"] != rows
    ):
        raise Failure(f"reconciliação da deduplicação não fecha: {summary}")
    return {**summary, "wall_ms": round(wall_ms)}


def export(
    client: Client, dataset_id: str, fmt: str, expected_rows: int, work: Path
) -> dict[str, Any]:
    _, created, _ = client.request(
        "POST",
        "/api/v1/exports",
        payload={"dataset_id": dataset_id, "kind": "rows", "format": fmt},
        expect=(202,),
    )
    finished, wall_ms = wait(client, f"/api/v1/exports/{created['id']}", 900)
    if finished["status"] != "succeeded" or finished["row_count"] != expected_rows:
        raise Failure(f"exportação {fmt}: {finished['status']}, {finished['row_count']} registros")
    target = work / f"exportacao.{fmt}"
    _, _, download_ms = client.request(
        "GET", f"/api/v1/exports/{created['id']}/download", sink=target, timeout=600
    )
    size = target.stat().st_size
    if size != finished["size_bytes"]:
        raise Failure(f"download com {size} bytes, esperado {finished['size_bytes']}")
    if fmt == "csv":
        with target.open("rb") as handle:
            lines = sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 20), b""))
        if lines != expected_rows + 1:
            raise Failure(f"CSV com {lines} linhas, esperado {expected_rows + 1}")
    elif target.read_bytes()[:2] != b"PK":
        raise Failure("XLSX baixado não é um arquivo ZIP")
    target.unlink()
    return {
        "rows": finished["row_count"],
        "size_bytes": size,
        "worker_ms": finished.get("duration_ms"),
        "wall_ms": round(wall_ms),
        "download_ms": round(download_ms),
    }


def refuses_oversized_export(client: Client, dataset_id: str, rows: int, limit: int) -> str:
    if rows <= limit:
        return "não se aplica (arquivo dentro do limite)"
    _, body, _ = client.request(
        "POST",
        "/api/v1/exports",
        payload={"dataset_id": dataset_id, "kind": "rows", "format": "csv"},
        expect=(400, 409, 413, 422),
    )
    code = body["error"]["code"]
    if code != "export_too_large":
        raise Failure(f"exportação acima do limite deveria ser recusada; veio {code}")
    return code


def count_rows(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 20), b"")) - 1


# ---------------------------------------------------------------- relatório


def _n(value: Any, digits: int = 0) -> str:
    """Número no formato brasileiro (1.234,5); vazio vira "—"."""
    if value is None:
        return "—"
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _rss(job: dict[str, Any]) -> str:
    return f"RSS {_n(job['peak_memory_mb'])} MB ({_n(job['start_memory_mb'])} MB)"


def summary_markdown(result: dict[str, Any]) -> str:
    large = result["csv_grande"]
    imported = large["importacao"]
    dedup = large["deduplicacao"]
    workbook = result["planilha"]
    book = workbook["importacao"]
    total = lambda item: (item["timings_ms"] or {}).get("total")  # noqa: E731
    lines = [
        "## Benchmark do fluxo completo",
        "",
        f"Base: `{result['base_url']}`. Tempos em milissegundos; RSS = pico do processo do "
        "worker durante o job (entre parênteses, no início dele).",
        "",
        "| Etapa | Resultado |",
        "| --- | --- |",
        f"| Upload de {large['arquivo']} ({_n(large['tamanho_mb'], 1)} MB) "
        f"| {_n(large['upload_ms'])} ms |",
        f"| Importação de {_n(imported['rows_total'])} registros | {_n(total(imported))} ms "
        f"({_n(imported['rows_per_second'])} registros/s); {_rss(imported)} |",
    ]
    for name, value in large["consultas_ms"].items():
        lines.append(f"| Consulta: {name.removesuffix('_ms').replace('_', ' ')} | {_n(value)} ms |")
    lines.append(
        f"| Deduplicação de {_n(dedup['rows_total'])} registros (vendedor + produto) "
        f"| {_n(total(dedup))} ms; {_n(dedup['rows_valid'])} mantidos; "
        f"{_rss(dedup)} |"
    )
    for key, label in (
        ("exportacao_csv", "Exportação CSV"),
        ("exportacao_xlsx", "Exportação XLSX"),
    ):
        item = result[key]
        lines.append(
            f"| {label} de {_n(item['rows'])} registros | worker {_n(item['worker_ms'])} ms; "
            f"download {_n(item['download_ms'])} ms; {_n(item['size_bytes'] / 1024 / 1024, 1)} MB |"
        )
    lines.append(
        f"| Planilha {workbook['arquivo']} ({_n(workbook['tamanho_mb'], 1)} MB): "
        f"{_n(book['rows_valid'])} registros | {_n(total(book))} ms; {_rss(book)} |"
    )
    return "\n".join(lines) + "\n"


def mb(path: Path) -> float:
    return round(path.stat().st_size / 1024 / 1024, 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--insecure", action="store_true", help="aceita certificado autoassinado")
    parser.add_argument("--large", type=Path, required=True, help="CSV grande (1 milhão de linhas)")
    parser.add_argument("--csv-limit", type=Path, required=True, help="CSV no limite do CSV")
    parser.add_argument("--xlsx-limit", type=Path, required=True, help="CSV no limite do XLSX")
    parser.add_argument("--workbook", type=Path, required=True, help="XLSX perto de 25 MB")
    parser.add_argument("--export-max-rows", type=int, default=500_000, help="EXPORT_MAX_ROWS")
    parser.add_argument("--work", type=Path, default=Path("benchmark-work"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    client = Client(args.base_url, args.insecure)
    result: dict[str, Any] = {"base_url": args.base_url}
    try:
        register(client)

        rows = count_rows(args.large)
        dataset, upload_ms = upload(client, args.large)
        imported = import_dataset(client, dataset)
        summary = job_summary(imported["job"])
        if summary["rows_valid"] != rows:
            raise Failure(f"importação: {summary['rows_valid']} válidos de {rows}")
        result["csv_grande"] = {
            "arquivo": args.large.name,
            "tamanho_mb": mb(args.large),
            "upload_ms": round(upload_ms),
            "importacao": {**summary, "wall_ms": imported["wall_ms"]},
            "consultas_ms": queries(client, dataset, rows),
            "exportacao_acima_do_limite": refuses_oversized_export(
                client, dataset, rows, args.export_max_rows
            ),
            "deduplicacao": deduplicate(client, dataset, rows),
        }
        print("csv_grande ok", flush=True)

        for key, path, fmt in (
            ("exportacao_csv", args.csv_limit, "csv"),
            ("exportacao_xlsx", args.xlsx_limit, "xlsx"),
        ):
            expected = count_rows(path)
            source, _ = upload(client, path)
            import_dataset(client, source)
            result[key] = export(client, source, fmt, expected, args.work)
            print(f"{key} ok", flush=True)

        book, book_upload_ms = upload(client, args.workbook)
        book_import = import_dataset(client, book, timeout=1800)
        result["planilha"] = {
            "arquivo": args.workbook.name,
            "tamanho_mb": mb(args.workbook),
            "upload_ms": round(book_upload_ms),
            "pre_visualizacao_ms": book_import["preview_ms"],
            "importacao": {**job_summary(book_import["job"]), "wall_ms": book_import["wall_ms"]},
        }
        print("planilha ok", flush=True)
    except Failure as exc:
        print(f"FALHA: {exc}", file=sys.stderr)
        print(f"BENCHMARK_STACK_PARCIAL {json.dumps(result, ensure_ascii=False)}")
        return 1

    print(f"BENCHMARK_STACK {json.dumps(result, ensure_ascii=False)}")
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
