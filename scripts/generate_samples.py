#!/usr/bin/env python3
"""Gerador reproduzível de datasets sintéticos para o DataFlow Analytics.

Todos os dados são fictícios: nomes são combinações aleatórias de listas genéricas e não
representam pessoas reais. Os CSV usam apenas a biblioteca padrão (roda sem instalar nada);
as planilhas XLSX (--xlsx) usam o openpyxl já instalado no backend.

Exemplos:
    python scripts/generate_samples.py                       # 1.000, 10.000 e 100.000 linhas
    python scripts/generate_samples.py --rows 1000 --seed 7  # outro conjunto reproduzível
    python scripts/generate_samples.py --rows 1000000 --only vendas --out /tmp/perf
    uv run --project backend python scripts/generate_samples.py --xlsx --rows 1000 --out samples
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import re
import zipfile
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

FIRST_NAMES = [
    "Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Heitor", "Isabela",
    "João", "Karina", "Lucas", "Mariana", "Nicolas", "Olívia", "Paulo", "Queila", "Rafael",
    "Sofia", "Thiago", "Úrsula", "Vinícius", "Wesley", "Yasmin",
]  # fmt: skip
LAST_NAMES = [
    "Almeida", "Barbosa", "Cardoso", "Dias", "Esteves", "Ferraz", "Gomes", "Holanda", "Ito",
    "Jardim", "Lima", "Moraes", "Nogueira", "Oliveira", "Pereira", "Queiroz", "Rocha", "Souza",
    "Teixeira", "Vieira",
]  # fmt: skip
TEAMS = ["Norte", "Sul", "Leste", "Oeste", "Centro"]
PRODUCTS = {
    "Informática": [("Notebook", 3200, 6500), ("Monitor 27", 900, 2100), ("Teclado", 80, 450), ("Mouse", 40, 280)],
    "Escritório": [("Cadeira ergonômica", 700, 2200), ("Mesa ajustável", 1100, 3400), ("Luminária", 90, 320)],
    "Software": [("Licença anual BI", 1500, 9000), ("Antivírus corporativo", 120, 600)],
    "Serviços": [("Instalação", 150, 900), ("Treinamento", 600, 4000), ("Suporte mensal", 300, 1800)],
}
SALE_STATUS = [("pago", 70), ("pendente", 15), ("cancelado", 8), ("estornado", 7)]
CHANNELS = [("Loja física", 30), ("E-commerce", 40), ("Televendas", 18), ("Parceiros", 12)]
CAMPAIGNS = ["Renovação 2025", "Black Friday", "Clientes inativos", "Upgrade de plano", "Pesquisa NPS"]
CALL_TYPES = [("Receptivo", 55), ("Ativo", 35), ("Chat", 10)]
CALL_STATUS = [("finalizado", 82), ("transferido", 10), ("abandonado", 8)]
CALL_RESULTS = {
    "finalizado": [("Venda realizada", 22), ("Dúvida resolvida", 40), ("Reclamação registrada", 18), ("Sem interesse", 20)],
    "transferido": [("Encaminhado ao suporte técnico", 70), ("Encaminhado ao financeiro", 30)],
    "abandonado": [("Cliente desligou", 100)],
}

START = date(2025, 1, 1)
DAYS = 365


def weighted(rng: random.Random, options: list[tuple[str, int]]) -> str:
    values, weights = zip(*options, strict=True)
    return rng.choices(values, weights=weights, k=1)[0]


def person(rng: random.Random, pool: list[str]) -> str:
    return rng.choice(pool)


def make_people(rng: random.Random, count: int) -> list[str]:
    names: set[str] = set()
    while len(names) < count:
        names.add(f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}")
    return sorted(names)


def br_decimal(value: Decimal) -> str:
    """1234.5 -> "1.234,50" (formato brasileiro, sem símbolo de moeda)."""
    integer, _, fraction = f"{value:.2f}".partition(".")
    grouped = f"{int(integer):,}".replace(",", ".")
    return f"{grouped},{fraction}"


def money(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(str(rng.uniform(low, high))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sales_rows(rng: random.Random, rows: int) -> Iterator[list[str]]:
    sellers = make_people(rng, 40)
    seller_team = {name: rng.choice(TEAMS) for name in sellers}
    categories = list(PRODUCTS)
    for _ in range(rows):
        seller = person(rng, sellers)
        category = rng.choice(categories)
        product, low, high = rng.choice(PRODUCTS[category])
        quantity = rng.choices([1, 2, 3, 4, 5, 10], weights=[50, 20, 12, 8, 6, 4])[0]
        sold_on = START + timedelta(days=rng.randrange(DAYS))
        yield [
            sold_on.strftime("%d/%m/%Y"),
            seller,
            seller_team[seller],
            product,
            category,
            str(quantity),
            br_decimal(money(rng, low, high) * quantity),
            weighted(rng, SALE_STATUS),
            weighted(rng, CHANNELS),
        ]


def call_rows(rng: random.Random, rows: int) -> Iterator[list[str]]:
    operators = make_people(rng, 60)
    operator_team = {name: rng.choice(TEAMS) for name in operators}
    for _ in range(rows):
        operator = person(rng, operators)
        status = weighted(rng, CALL_STATUS)
        moment = datetime.combine(START + timedelta(days=rng.randrange(DAYS)), datetime.min.time())
        moment += timedelta(seconds=rng.randrange(8 * 3600, 20 * 3600))
        duration = int(rng.lognormvariate(5.3, 0.6)) if status != "abandonado" else rng.randrange(5, 90)
        yield [
            moment.strftime("%d/%m/%Y %H:%M:%S"),
            operator,
            operator_team[operator],
            rng.choice(CAMPAIGNS),
            weighted(rng, CALL_TYPES),
            str(duration),
            status,
            weighted(rng, CALL_RESULTS[status]),
        ]


def quality_rows(rng: random.Random, rows: int) -> Iterator[list[str]]:
    """Vendas com problemas propositais e documentados (para demonstrar rejeições)."""
    previous: list[list[str]] = []
    for index, row in enumerate(sales_rows(rng, rows)):
        roll = rng.random()
        if previous and roll < 0.04:
            # Duplicidade exata de um registro anterior.
            yield list(rng.choice(previous))
            continue
        if roll < 0.06:
            row[1] = f"  {row[1]}   "  # espaços excedentes
        elif roll < 0.08:
            row[0] = rng.choice(["31/02/2025", "2025-13-01", "ontem", "00/00/0000"])  # datas inválidas
        elif roll < 0.10:
            row[6] = rng.choice([row[6].replace(".", ""), f"R$ {row[6]}", f" {row[6]} ", row[6].replace(",", ".")])
        elif roll < 0.13:
            row[rng.choice([2, 4, 8])] = ""  # valores nulos
        elif roll < 0.14:
            row[5] = rng.choice(["dois", "1,5", "-"])  # quantidade inconsistente
        elif roll < 0.15:
            row = row[: rng.randrange(3, 7)]  # registro incompleto
        elif roll < 0.16:
            row = [""] * 9  # linha totalmente vazia
        elif roll < 0.17:
            row[3] = row[3].upper()  # caixa inconsistente
        if index % 50 == 0:
            previous.append(list(row))
        yield row


DATASETS: dict[str, tuple[list[str], Callable[[random.Random, int], Iterator[list[str]]], str]] = {
    "vendas": (
        ["data_venda", "vendedor", "equipe", "produto", "categoria", "quantidade", "valor", "status", "canal"],
        sales_rows,
        ";",
    ),
    "atendimentos": (
        ["data_atendimento", "operador", "equipe", "campanha", "tipo_atendimento", "duracao_segundos", "status", "resultado"],
        call_rows,
        ",",
    ),
    "qualidade": (
        ["data_venda", "vendedor", "equipe", "produto", "categoria", "quantidade", "valor", "status", "canal"],
        quality_rows,
        ";",
    ),
}


def write_dataset(name: str, rows: int, seed: int, out_dir: Path) -> Path:
    header, factory, delimiter = DATASETS[name]
    # Seed derivada do nome: cada dataset é reproduzível de forma independente.
    rng = random.Random(f"{seed}-{name}-{rows}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}_{rows}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        for row in factory(rng, rows):
            writer.writerow(row)
    return path


XLSX_TITLE = "Relatório de vendas — dados fictícios gerados por scripts/generate_samples.py"
FIXED_ZIP_TIME = (2025, 1, 1, 0, 0, 0)


def _typed_sale(row: list[str]) -> list[object]:
    """Linha de vendas com tipos de planilha: data, inteiro e decimal reais (não texto)."""
    day, month, year = (int(part) for part in row[0].split("/"))
    value = Decimal(row[6].replace(".", "").replace(",", "."))
    return [date(year, month, day), *row[1:5], int(row[5]), value, *row[7:]]


def _typed_call(row: list[str]) -> list[object]:
    return [datetime.strptime(row[0], "%d/%m/%Y %H:%M:%S"), *row[1:5], int(row[5]), *row[6:]]


def _normalize_zip(path: Path) -> None:
    """Datas fixas nas entradas do ZIP: mesma seed e tamanho geram arquivos idênticos."""
    entries: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(path) as source:
        for info in source.infolist():
            entries.append((info, source.read(info.filename)))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for info, data in entries:
            if info.filename == "docProps/core.xml":
                # O openpyxl grava a hora do salvamento em "modified".
                data = re.sub(
                    rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                    rb"\g<1>2025-01-01T00:00:00Z\g<2>",
                    data,
                )
            fixed = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            fixed.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(fixed, data)
    path.write_bytes(buffer.getvalue())


def write_workbook(rows: int, seed: int, out_dir: Path) -> Path:
    """Planilha com as mesmas vendas do CSV equivalente, atendimentos e uma aba de fórmulas.

    - "Vendas": título na linha 1, linha 2 vazia e cabeçalho na linha 3 (exercita a escolha
      da linha do cabeçalho). Datas, quantidades e valores gravados como tipos reais.
    - "Atendimentos": cabeçalho na linha 1, data e hora reais.
    - "Totais": fórmulas SOMASE sem valor calculado salvo (o openpyxl não calcula). O DataFlow
      não executa fórmulas, então essas linhas são rejeitadas com o motivo "fórmula sem valor".
    """
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise SystemExit(
            "XLSX requer openpyxl: uv run --project backend python scripts/generate_samples.py --xlsx"
        ) from exc

    workbook = Workbook(write_only=True)
    sales_header, sales_factory, _ = DATASETS["vendas"]
    calls_header, calls_factory, _ = DATASETS["atendimentos"]

    sales = workbook.create_sheet("Vendas")
    sales.append([XLSX_TITLE])
    sales.append([])
    sales.append(sales_header)
    for row in sales_factory(random.Random(f"{seed}-vendas-{rows}"), rows):
        sales.append(_typed_sale(row))

    calls = workbook.create_sheet("Atendimentos")
    calls.append(calls_header)
    for row in calls_factory(random.Random(f"{seed}-atendimentos-{rows}"), rows):
        calls.append(_typed_call(row))

    totals = workbook.create_sheet("Totais")
    totals.append(["equipe", "total_vendas"])
    last = rows + 3
    for index, team in enumerate(TEAMS, start=2):
        totals.append([team, f"=SUMIF(Vendas!C4:C{last},A{index},Vendas!G4:G{last})"])

    workbook.properties.creator = "scripts/generate_samples.py"
    workbook.properties.created = datetime(2025, 1, 1)
    workbook.properties.modified = datetime(2025, 1, 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"vendas_atendimentos_{rows}.xlsx"
    workbook.save(path)
    _normalize_zip(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, nargs="+", default=[1_000, 10_000, 100_000])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--only", choices=sorted(DATASETS), nargs="+")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "samples" / "generated")
    parser.add_argument("--xlsx", action="store_true", help="gera planilhas XLSX em vez de CSV")
    args = parser.parse_args()
    if args.xlsx:
        for rows in args.rows:
            path = write_workbook(rows, args.seed, args.out)
            print(f"{path}  ({path.stat().st_size / 1024:,.0f} KB)")
        return
    for name in args.only or sorted(DATASETS):
        for rows in args.rows:
            path = write_dataset(name, rows, args.seed, args.out)
            print(f"{path}  ({path.stat().st_size / 1024:,.0f} KB)")


if __name__ == "__main__":
    main()
