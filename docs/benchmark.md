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

## Resultados — fluxo completo com infraestrutura real (30/10/2026)

Medido pelo E2E `e2e/tests/large-file.spec.ts`, que envia `vendas_100000.csv` pela interface com o Docker Compose completo (Caddy → API → MinIO → Redis → worker Celery → PostgreSQL). A CI registra os números na linha `BENCHMARK_E2E` do log ([execução 41124382410](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41124382410), commit `34a5abb`).

**Ambiente:** GitHub Actions, `ubuntu-24.04`, 4 vCPUs, 15 GiB de RAM. Worker limitado a 2 CPUs e 2 GB (padrões do Compose), concorrência 2. PostgreSQL 17, Redis 8.8, MinIO (Chainguard), Chromium via Playwright.

**Arquivo:** 8,06 MB, 100.000 registros → 100.000 válidos, 0 rejeitados. É **uma única execução** em um runner compartilhado: trate como ordem de grandeza, não como média.

| Etapa | Tempo | O que mede |
| --- | --- | --- |
| Upload pela interface | 308 ms | Do envio no navegador até a tela mostrar o arquivo armazenado no MinIO. |
| Recebimento no servidor | 40 ms | Gravação em disco e inspeção (hash, UTF-8, delimitador). Parte do upload acima. |
| Leitura e validação no worker | 31 ms | Baixar o original do MinIO e conferir o SHA-256. |
| Processamento | 681 ms | Leitura e tokenização 451 ms, conversão de tipos 166 ms, escrita Parquet 42 ms. |
| Persistência | 11 ms | Checksum e envio do Parquet ao MinIO. Não inclui a transação de publicação no PostgreSQL. |
| **Total do job** | **741 ms** | Do início da execução no worker até a publicação da versão: **~135 mil registros/s**. |
| Do clique até o resultado na tela | 2.163 ms | Inclui a fila e o intervalo de atualização da tela (1,5 s). Limite superior, não comparável ao total do job. |
| Consulta com cache vazio | 69 ms | `page=2000` (`OFFSET 99.950`), ordenada por decimal, incluindo baixar o Parquet para o cache. |
| Consulta com cache | 60 ms | A mesma consulta, medida a partir do cliente, passando pelo Caddy. |

**Memória:** pico de **312,9 MB de RSS** no processo do worker. É o pico do processo desde que ele iniciou: inclui o interpretador e as bibliotecas nativas (Polars, Arrow) e pode incluir jobs anteriores do mesmo processo, pois outros testes E2E rodaram antes. Não é o custo isolado deste job. Os ~40 MB da tabela anterior são outra medida: só o heap Python (`tracemalloc`), sem a memória nativa.

## Pendente

- Medições com 1 milhão de linhas e com arquivos próximos do limite de 100 MB. Até lá, não há evidência de como a memória e o tempo escalam acima de 100 mil linhas.
- Repetir a medição várias vezes para obter média e variação.
