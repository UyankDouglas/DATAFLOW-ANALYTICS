"""Popula uma instalação em execução com o workspace de demonstração, pela API pública.

Cria (ou entra na) conta de demonstração e envia os arquivos fictícios de `samples/`: vendas,
atendimentos, o arquivo com problemas de qualidade e a aba "Atendimentos" da planilha. Processa
tudo pelo worker, aplica um conjunto de regras (limpeza e deduplicação) às vendas, cria o
dashboard "Comercial" e pede uma exportação. Nada é inserido direto no banco: o resultado é o
mesmo de uma pessoa usando a interface.

    DEMO_PASSWORD='uma-senha-forte' python3 scripts/seed_demo.py --base-url http://localhost:8080

Sem `DEMO_PASSWORD`, gera uma senha aleatória e a mostra uma única vez, no fim. Se a conta já
tiver datasets, não faz nada (o seed não duplica dados).
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_stack import Client, Failure, import_dataset, upload, wait

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
SUM = {"aggregation": "sum", "column": "valor"}


def sign_in(client: Client, email: str, password: str) -> bool:
    """Entra na conta; cria se não existir. Devolve True quando a conta é nova."""
    client.request("GET", "/api/v1/auth/csrf")
    status, _, _ = client.request(
        "POST",
        "/api/v1/auth/register",
        payload={
            "full_name": "Demonstração",
            "email": email,
            "password": password,
            "workspace_name": "DataFlow Demo",
        },
        expect=(201, 409),
    )
    if status == 201:
        return True
    client.request("POST", "/api/v1/auth/login", payload={"email": email, "password": password})
    return False


def dashboard(client: Client, sales: str) -> str:
    widgets = [
        {
            "title": "Valor total",
            "chart_type": "kpi",
            "size": "small",
            "query": {"metrics": [SUM]},
        },
        {
            "title": "Vendas pagas",
            "chart_type": "kpi",
            "size": "small",
            "query": {
                "metrics": [{"aggregation": "count"}],
                "filters": [{"column": "status", "operator": "eq", "value": "pago"}],
            },
        },
        {
            "title": "Valor médio",
            "chart_type": "kpi",
            "size": "small",
            "query": {"metrics": [{"aggregation": "avg", "column": "valor"}]},
        },
        {
            "title": "Vendedores",
            "chart_type": "kpi",
            "size": "small",
            "query": {"metrics": [{"aggregation": "count_distinct", "column": "vendedor"}]},
        },
        {
            "title": "Valor por mês",
            "chart_type": "area",
            "size": "medium",
            "query": {
                "metrics": [SUM],
                "dimension": {"column": "data_venda", "granularity": "month"},
            },
        },
        {
            "title": "Valor por equipe",
            "chart_type": "bar_horizontal",
            "size": "medium",
            "query": {"metrics": [SUM], "dimension": {"column": "equipe"}},
        },
        {
            "title": "Vendas por canal",
            "chart_type": "donut",
            "size": "medium",
            "query": {"metrics": [{"aggregation": "count"}], "dimension": {"column": "canal"}},
        },
        {
            "title": "Principais vendedores",
            "chart_type": "table",
            "size": "medium",
            "query": {
                "metrics": [{"aggregation": "count"}, SUM],
                "dimension": {"column": "vendedor"},
                "limit": 8,
            },
        },
    ]
    _, created, _ = client.request(
        "POST",
        "/api/v1/dashboards",
        payload={
            "name": "Comercial",
            "description": "Vendas fictícias por mês, equipe, canal e vendedor",
            "dataset_id": sales,
            "widgets": widgets,
        },
        expect=(201,),
    )
    return created["id"]


def clean_sales(client: Client, sales: str) -> dict[str, int]:
    _, detail, _ = client.request("GET", f"/api/v1/datasets/{sales}")
    _, tset, _ = client.request(
        "POST",
        f"/api/v1/datasets/{sales}/transformation-sets",
        payload={
            "name": "Limpeza de vendas",
            "description": "Remove espaços, descarta cancelamentos e duplicidades",
            "rules": [
                {"operation": "trim", "columns": ["vendedor", "produto", "equipe"]},
                {
                    "operation": "filter_rows",
                    "match": "all",
                    "conditions": [{"column": "status", "operator": "ne", "value": "cancelado"}],
                },
                {
                    "operation": "deduplicate",
                    "columns": ["data_venda", "vendedor", "produto", "valor"],
                    "keep": "first",
                },
            ],
        },
        expect=(201,),
    )
    _, job, _ = client.request(
        "POST",
        f"/api/v1/datasets/{sales}/transform-jobs",
        payload={
            "source_version_id": detail["current_version_id"],
            "transformation_set_id": tset["id"],
        },
        expect=(202,),
    )
    finished, _ = wait(client, f"/api/v1/jobs/{job['id']}", 600)
    if finished["status"] != "succeeded":
        raise Failure(f"transformação terminou como {finished['status']}")
    return {"validos": finished["rows_valid"], "filtrados": finished["rows_filtered"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--insecure", action="store_true", help="aceita certificado autoassinado")
    parser.add_argument("--email", default=os.environ.get("DEMO_EMAIL", "demo@example.com"))
    args = parser.parse_args()
    password = os.environ.get("DEMO_PASSWORD") or f"Demo-{secrets.token_urlsafe(12)}"
    client = Client(args.base_url, args.insecure)
    try:
        new_account = sign_in(client, args.email, password)
        _, existing, _ = client.request("GET", "/api/v1/datasets?page_size=1")
        if existing["total"]:
            print(f"A conta {args.email} já tem {existing['total']} dataset(s); nada foi criado.")
            return 0

        created: dict[str, str] = {}
        for file, name in (
            ("vendas_1000.csv", "Vendas 2025"),
            ("atendimentos_1000.csv", "Atendimentos 2025"),
            ("qualidade_1000.csv", "Vendas com problemas"),
        ):
            dataset, _ = upload(client, SAMPLES / file, name)
            import_dataset(client, dataset)
            created[name] = dataset
            print(f"{name}: processado", flush=True)

        workbook, _ = upload(client, SAMPLES / "vendas_atendimentos_1000.xlsx", "Planilha - Vendas")
        import_dataset(client, workbook)
        _, sheet, _ = client.request(
            "POST",
            f"/api/v1/datasets/{workbook}/sheets",
            payload={"sheet": "Atendimentos", "name": "Planilha - Atendimentos"},
            expect=(201,),
        )
        import_dataset(client, sheet["dataset"]["id"])
        print("Planilha: abas Vendas e Atendimentos processadas", flush=True)

        sales = created["Vendas 2025"]
        cleaned = clean_sales(client, sales)
        print(f"Limpeza das vendas: {cleaned['validos']} registros na versão 2", flush=True)
        dashboard_id = dashboard(client, sales)
        client.request(
            "POST",
            "/api/v1/exports",
            payload={"dataset_id": sales, "kind": "rows", "format": "xlsx"},
            expect=(202,),
        )
    except Failure as exc:
        print(f"FALHA: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"Pronto. Entre em {args.base_url}/entrar com {args.email}")
    if new_account and not os.environ.get("DEMO_PASSWORD"):
        print(f"Senha gerada (anote, não aparece de novo): {password}")
    print(f"Dashboard: {args.base_url}/dashboards/{dashboard_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
