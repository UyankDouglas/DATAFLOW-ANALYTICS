# Benchmark

Números **medidos**, nunca estimados. Cada linha registra o ambiente em que foi obtida.

## Como reproduzir

```bash
python scripts/generate_samples.py --rows 100000          # seed 42, determinístico
cd backend
uv run python -m app.scripts.benchmark_pipeline \
  ../samples/generated/vendas_100000.csv \
  ../samples/generated/atendimentos_100000.csv \
  ../samples/generated/qualidade_100000.csv
```

O script executa as mesmas funções do worker: inspeção do upload, amostra + inferência, pipeline completo (tokenização, validação, conversão de tipos com Polars, escrita Parquet) e uma consulta DuckDB ordenada com `OFFSET 5000`. Tempo e memória são medidos em **execuções separadas** (o `tracemalloc` distorce o tempo).

## Resultados — Fase 1 (29/10/2026)

**Ambiente:** Windows 10 Pro, CPU Intel Family 6 Model 79 (Broadwell-EP, 28 threads lógicas), 12 GB RAM, Python 3.13.12, Polars 2.1.0, DuckDB 1.5.6, PyArrow 26, lote de 50.000 registros. Pipeline executado em processo (sem rede, banco ou S3).

| Arquivo | Tamanho | Registros | Válidos | Rejeitados | Inspeção do upload | Pipeline total | Leitura | Conversão | Escrita | Consulta paginada | Registros/s | Pico de memória Python | Parquet |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vendas_100000.csv | 8,06 MB | 100.000 | 100.000 | 0 | 0,049 s | 0,896 s | 0,533 s | 0,196 s | 0,149 s | 0,125 s | 111.629 | 43,3 MB | 1,10 MB |
| atendimentos_100000.csv | 9,33 MB | 100.000 | 100.000 | 0 | 0,052 s | 0,735 s | 0,529 s | 0,069 s | 0,118 s | 0,130 s | 136.101 | 38,2 MB | 1,41 MB |
| qualidade_100000.csv | 7,92 MB | 100.000 | 97.932 | 2.068 | 0,049 s | 0,740 s | 0,475 s | 0,038 s | 0,205 s | 0,126 s | 135.076 | 41,3 MB | 1,17 MB |

Observações:

- No `qualidade_100000.csv` os tipos foram inferidos pela amostra; como a amostra contém valores sujos (`R$ 99,90`, `ontem`), as colunas correspondentes ficaram como texto e só houve rejeições estruturais (1.041 linhas vazias, 1.027 com campos a menos). Forçando tipos na pré-visualização, as rejeições de tipo aparecem — coberto pelos testes e pelo E2E.
- Uma otimização registrada: a primeira versão do leitor fazia `append` por célula (4,7 s para 100 mil linhas, medidos com `tracemalloc` ativo). A transposição por lote com `zip` reduziu a leitura para ~0,5 s.
- O pico do processo (RSS) é medido por `resource` e só está disponível em Linux; no Windows o campo fica `null`.

## Pendente

- **Fluxo completo com infraestrutura real** (upload HTTP → MinIO → worker Celery → PostgreSQL → consulta via API) dentro do Docker Compose: depende de um host com Docker. O job já registra essas métricas em `metrics.timings_ms` (envio, leitura e validação, processamento, persistência, total, registros/s e memória), visíveis na tela do processamento. A tabela acima será complementada com essa medição.
- Testes com 1 milhão de linhas e com arquivos próximos do limite de 100 MB.
