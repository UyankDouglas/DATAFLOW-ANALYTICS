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

Para XLSX e transformações (Fase 2):

```bash
uv run --project backend python scripts/generate_samples.py --xlsx --rows 100000
cd backend
uv run python -m app.scripts.benchmark_etl ../samples/generated/vendas_atendimentos_100000.xlsx
```

O `benchmark_etl` inspeciona a planilha, gera a prévia da aba "Vendas", importa a aba inteira, transforma a versão resultante (remover espaços em 6 colunas, filtro `status ≠ cancelado`, coluna derivada `valor ÷ quantidade` e deduplicação por vendedor + produto) e confere a análise de duplicidades do DuckDB contra a deduplicação do pipeline.

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

Medido pelo E2E `e2e/tests/large-file.spec.ts`, que envia `vendas_100000.csv` pela interface com o Docker Compose completo (Caddy → API → MinIO → Redis → worker Celery → PostgreSQL). A CI registra os números na linha `BENCHMARK_E2E` do log.

**Ambiente:** GitHub Actions, `ubuntu-24.04`, 4 vCPUs, 15 GiB de RAM. Worker limitado a 2 CPUs e 2 GB, concorrência 2. PostgreSQL 17, Redis 8.8, MinIO (Chainguard), Chromium via Playwright.

**Arquivo:** 8,06 MB, 100.000 registros → 100.000 válidos, 0 rejeitados, nas três execuções.

| Etapa | [Dev, `34a5abb`](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41124382410) | [Dev, `a11e2fd`](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41126313886) | [Produção com HTTPS, `a11e2fd`](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41126313886) | O que mede |
| --- | --- | --- | --- | --- |
| Upload pela interface | 308 ms | 250 ms | 363 ms | Do envio no navegador até a tela mostrar o arquivo armazenado no MinIO. |
| Recebimento no servidor | 40 ms | 46 ms | 114 ms | Gravação em disco e inspeção (hash, UTF-8, delimitador). Parte do upload acima. |
| Leitura e validação no worker | 31 ms | 42 ms | 30 ms | Baixar o original do MinIO e conferir o SHA-256. |
| Processamento | 681 ms | 957 ms | 888 ms | Leitura e tokenização, conversão de tipos e escrita Parquet. |
| Persistência | 11 ms | 18 ms | 14 ms | Checksum e envio do Parquet ao MinIO. Não inclui a transação de publicação no PostgreSQL. |
| **Total do job** | **741 ms** | **1.046 ms** | **955 ms** | Do início da execução no worker até a publicação da versão. |
| **Registros/s** | **134.953** | **95.602** | **104.712** | Registros recebidos ÷ total do job. |
| Do clique até o resultado na tela | 2.163 ms | 2.248 ms | 2.226 ms | Inclui a fila e o intervalo de atualização da tela (1,5 s). Limite superior, não comparável ao total do job. |
| Consulta com cache vazio | 69 ms | 124 ms | 88 ms | `page=2000` (`OFFSET 99.950`), ordenada por decimal, incluindo baixar o Parquet para o cache. |
| Consulta com cache | 60 ms | 102 ms | 97 ms | A mesma consulta, medida a partir do cliente, passando pelo Caddy. |
| Pico de RSS do worker | 312,9 MB | 312,3 MB | 312,7 MB | Ver a observação abaixo. |

**Como ler:** são três execuções em runners compartilhados, com variação de cerca de 40% no total do job. Trate como ordem de grandeza. A amostra não permite afirmar diferença entre desenvolvimento e produção: o resultado de produção ficou entre os dois de desenvolvimento.

**Memória:** o pico foi estável, em torno de 313 MB, mas é o pico do processo desde que ele iniciou: inclui o interpretador e as bibliotecas nativas (Polars, Arrow) e pode incluir jobs anteriores do mesmo processo, pois outros testes E2E rodaram antes. Não é o custo isolado deste job. Os ~40 MB da tabela anterior são outra medida: só o heap Python (`tracemalloc`), sem a memória nativa.

## Resultados — Fase 2: XLSX e transformações (03/11/2026)

**Ambiente:** o mesmo da Fase 1 (Windows 10 Pro, Intel Family 6 Model 79, Python 3.13.12, Polars 2.1.0, DuckDB 1.5.6), openpyxl 3.1.5, lote de 50.000 registros, em processo (sem rede, banco ou S3). Duas execuções depois das correções abaixo; a tabela mostra a faixa.

**Arquivo:** `vendas_atendimentos_100000.xlsx`, 8,79 MB, 3 abas; aba "Vendas" com 100.000 registros (os mesmos de `vendas_100000.csv`) e cabeçalho detectado na linha 3.

| Etapa | Tempo | Resultado |
| --- | --- | --- |
| Inspeção do upload (contêiner + abas + cabeçalho) | 0,02–0,05 s | 3 abas listadas |
| Prévia (1.000 registros + inferência) | 0,94–0,97 s | estimativa de 100.000 registros, intervalo `A3:I100003` |
| Importação da aba inteira → Parquet | 40,4–40,5 s (≈ 2.470 registros/s) | 100.000 válidos, reconciliação consistente |
| Transformação com 4 regras | 0,90–1,11 s (90–111 mil registros/s) | 100.000 = 480 válidos + 0 rejeitados + 8.033 filtrados + 91.487 duplicados |
| — dos quais deduplicação | 0,53–0,60 s | segunda passada sobre o resultado inteiro |
| Análise de duplicidades (DuckDB) | 0,08–0,11 s | 99.520 duplicados por vendedor + produto, **igual** ao pipeline só com a deduplicação |

Observações:

- **Otimização registrada:** a primeira medição deu inspeção em 13,3 s, prévia em 27,5 s e importação em 72,4 s. O openpyxl, quando a aba não declara `<dimension>` (comum em planilhas geradas por bibliotecas; o Excel sempre declara), só percebe a ausência no fim dos dados — ou seja, lia todas as abas inteiras só para abrir o arquivo. O leitor passou a parar no início dos dados (`_declared_size` em `processing/xlsx.py`), com o mesmo resultado quando a tag existe.
- **Regressão encontrada e corrigida no CSV:** com a obrigatoriedade e o valor para vazios, a conversão de tipos de `vendas_100000.csv` passou de 0,22 s (código da Fase 1, medido de novo na mesma máquina) para 0,40 s, porque o código de erro de cada coluna embutia de novo a conversão. Reestruturada em etapas sobre colunas já calculadas, ficou em 0,14–0,21 s; o pipeline completo voltou a 0,8–1,0 s (≈ 100 mil registros/s).
- **XLSX é cerca de 40 vezes mais lento que CSV** (≈ 2.470 contra ≈ 100 mil registros/s nas mesmas vendas). A planilha é lida duas vezes em paralelo — valores salvos e fórmulas — para distinguir fórmula sem valor (ADR-014), e o openpyxl interpreta cada célula em Python. É a razão do limite de 25 MB e do progresso de XLSX ser só a contagem de registros. Não foi medido um arquivo perto de 25 MB.
- A transformação lê Parquet tipado e roda em Polars, então custa o mesmo que a importação de CSV; a deduplicação domina o tempo porque precisa do resultado inteiro.
- Os números de duplicados são altos porque a chave vendedor + produto tem só ~480 combinações nos dados sintéticos; servem para medir custo e conferir contagens, não como cenário realista.

## Resultados — Fase 3: qualidade e Data Explorer (03/11/2026)

Medido pelo mesmo `benchmark_pipeline` (que passou a calcular o relatório de qualidade e uma consulta do explorer depois do pipeline), no mesmo ambiente, em duas execuções.

| Arquivo | Relatório de qualidade | Nota | Consulta filtrada (página + contagem) |
| --- | --- | --- | --- |
| vendas_100000.csv | 0,19–0,20 s | 100,0 | 0,11–0,12 s |
| qualidade_100000.csv | 0,25–0,28 s | 98,2 | 0,11–0,12 s |

A consulta usa um filtro "não é nulo" e uma busca por `a` nas colunas de texto, ordenada pela última coluna, e devolve a primeira página de 50 mais o `count(*)` filtrado. Como a busca casa com praticamente todos os registros, a medida é de varredura completa, o pior caso para a contagem. O relatório inclui o perfil de todas as colunas, a distribuição de nulos, os duplicados restantes em todas as colunas e o agrupamento das exclusões.

No fluxo completo da CI com a Fase 3 ([execução 41683893654](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41683893654)), o job do `vendas_100000.csv` levou 929 ms em desenvolvimento e 702 ms em produção, comparável às execuções da tabela de 30/10 (741 a 1.046 ms) dado o ruído dos runners. Esse tempo vai até a publicação da versão: o relatório de qualidade é calculado logo depois e não entra nele.

## Resultados — Fase 4: consultas dos dashboards (03/11/2026)

Medido pelo mesmo `benchmark_pipeline`, que passou a executar as consultas analíticas sobre o Parquet publicado, no mesmo ambiente, em duas execuções. As colunas são as que um usuário escolheria: medida `valor` (decimal) ou `duracao_segundos` (inteiro), categoria `vendedor` ou `operador` e data `data_venda` (data) ou `data_atendimento` (data e hora).

| Consulta (100 mil registros) | vendas_100000.csv | atendimentos_100000.csv |
| --- | --- | --- |
| KPIs: contagem, soma, média, mínimo, máximo e contagem distinta | 0,046–0,048 s | 0,039–0,040 s |
| Soma por categoria, 10 maiores + "Outros" | 0,072–0,081 s | 0,053–0,055 s |
| Série mensal | 0,050–0,054 s | 0,049 s |
| Comparação entre períodos (30 dias contra os 30 anteriores) | 0,050–0,052 s | 0,048–0,057 s |
| Comparação por categoria, 8 maiores + "Outros" | 0,084–0,091 s | 0,085–0,087 s |

O tempo é só o da consulta, com o Parquet já em disco. Na API soma-se o download do Parquet para o cache na primeira consulta de cada versão, que é o mesmo do explorer (ver a tabela do fluxo completo). O agrupamento com "Outros" faz uma segunda consulta, sobre os registros fora dos grupos mostrados. Com 100 mil registros, recalcular a cada abertura cabe folgado nos 10 s de tempo-limite (ADR-021). Arquivos muito maiores ainda não foram medidos.

## Resultados — Fase 5: exportações (03/11/2026)

Medido pelo mesmo `benchmark_pipeline`, que passou a exportar a versão inteira com o mesmo leitor (DuckDB em lotes de 5 mil) e os mesmos escritores do worker, no mesmo ambiente, em duas execuções.

| Exportação (100 mil registros) | vendas_100000.csv (9 colunas) | atendimentos_100000.csv (8 colunas) |
| --- | --- | --- |
| CSV para Excel em português | 1,96–2,02 s | 1,59–1,67 s |
| XLSX com números e datas formatados | 27,3–28,6 s | 23,5 s |

O XLSX é cerca de 13 vezes mais lento, porque o openpyxl monta cada célula em Python. Numa medição isolada com as mesmas 900 mil células, a escrita levou 24,8 s com formato em todas as células, 21,3 s só tipando o texto e 17,4 s com valores puros. A formatação custa cerca de 30%, e o limite de 100 mil registros para XLSX segura o pior caso em torno de meio minuto, em segundo plano. O CSV ficou com 500 mil registros (≈ 10 s, por extrapolação linear, não medido).

## Resultados — Fase 6: 1 milhão de registros, em processo (03/11/2026)

Medido pelo mesmo `benchmark_pipeline`, no mesmo ambiente das fases anteriores (Windows 10 Pro, Intel Family 6 Model 79, Python 3.13.12, Polars 2.1.0, DuckDB 1.5.6, lote de 50.000 registros), uma execução. As exportações passaram a respeitar os limites que a API aceita, como o worker faz: até 500 mil registros em CSV e 100 mil em XLSX.

**Arquivo:** `vendas_1000000.csv` (`generate_samples.py --rows 1000000 --only vendas`, seed 42), 80,3 MB, 1.000.000 registros → 1.000.000 válidos; Parquet de 10,9 MB.

| Etapa | Tempo |
| --- | --- |
| Inspeção do upload (hash, UTF-8, delimitador) | 0,42 s |
| Prévia (1.000 registros + inferência) | 0,12 s |
| Pipeline completo | **8,1 s (123.344 registros/s)** — leitura 5,1 s, conversão 1,5 s, escrita 1,4 s |
| Pico do heap Python no pipeline (`tracemalloc`) | **43,3 MB**, o mesmo das 100 mil linhas: a leitura é por lotes |
| Página ordenada (`OFFSET 5000`) | 0,23 s |
| Relatório de qualidade completo | 0,88 s |
| Explorer: filtro + busca + contagem (varredura completa) | 0,25 s |
| Dashboards: KPIs · por categoria com "Outros" · série mensal · comparação · comparação por categoria | 0,10 · 0,24 · 0,13 · 0,10 · 0,19 s |
| Exportação CSV de 500 mil registros (o limite) | 10,1 s |
| Exportação XLSX de 100 mil registros (o limite) | 28,0 s |

Comparado às 100 mil linhas, o pipeline escalou de forma linear (0,8–1,0 s → 8,1 s) e as consultas, abaixo disso (0,05–0,09 s → 0,10–0,25 s). Todas ficaram longe do tempo-limite de 10 s. O CSV de 500 mil confirmou a extrapolação da Fase 5 (≈ 10 s). O pico de RSS não é medido no Windows; o do processo do worker em contêiner vem da CI.

## Fluxo completo com infraestrutura real: `benchmark_stack` (Fase 6)

`scripts/benchmark_stack.py` mede o fluxo inteiro contra uma instalação em execução, só pela API pública e com a biblioteca padrão do Python. Ele cadastra uma conta descartável e envia os arquivos em streaming. Depois processa, consulta, deduplica e exporta, e confere as contagens em cada etapa: falha se algo não bater. O job `benchmark` da CI roda o script contra o Docker Compose de desenvolvimento, com o worker limitado a 2 CPUs e 2 GB:

```bash
python3 scripts/generate_samples.py --rows 1000000 500000 100000 --only vendas
uv run --no-project --with openpyxl==3.1.5 python scripts/generate_samples.py --xlsx --rows 280000
python3 scripts/benchmark_stack.py --base-url http://localhost:8080 \
  --large samples/generated/vendas_1000000.csv \
  --csv-limit samples/generated/vendas_500000.csv \
  --xlsx-limit samples/generated/vendas_100000.csv \
  --workbook samples/generated/vendas_atendimentos_280000.xlsx --out benchmark-stack.json
```

| Etapa | O que mede |
| --- | --- |
| CSV de 1 milhão (≈ 80 MB) | upload pela borda, job de importação (tempos por etapa, registros/s, pico de RSS do processo do worker durante o job e RSS no início dele), página final com e sem cache, explorer com filtro e busca, KPIs, agrupamento com "Outros" e série mensal |
| Exportação acima do limite | o pedido de CSV da versão de 1 milhão precisa ser recusado com `export_too_large` |
| Deduplicação de 1 milhão | transformação versão → versão por vendedor + produto; a reconciliação precisa fechar (ADR-016) |
| Exportações nos limites | CSV de 500 mil e XLSX de 100 mil gerados pelo worker, baixados pela API e conferidos (linhas, tamanho, assinatura ZIP) |
| Planilha perto de 25 MB | `vendas_atendimentos_280000.xlsx` (24,7 MiB, gerada de forma determinística): prévia e importação da aba "Vendas" |

Os números entram aqui quando a CI deste pull request rodar; o resumo sai no `$GITHUB_STEP_SUMMARY` e no artefato `benchmark-stack`. Localmente, sem Docker, o script foi validado de ponta a ponta contra a API com infraestrutura simulada e arquivos menores (100 mil linhas e a planilha de 8,8 MB). Esses números não servem de referência, porque o S3 e o worker rodam no mesmo processo.

## Memória da deduplicação de 1 milhão (Fase 6)

Na primeira execução do job `benchmark` na CI ([execução 41820017555](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41820017555)), a deduplicação de 1 milhão de registros por vendedor + produto registrou 1.357,3 MB de pico de RSS no processo do worker, e o cgroup do worker chegou a 1.501.970.432 bytes, com limite de 2 GB. A importação da planilha, que rodou depois no mesmo processo, registrou os mesmos 1.357,3 MB: era o pico herdado, corrigido pela ADR-030.

Medido localmente (04/11/2026, Windows 10, Python 3.13, Polars 2.1.0), com o mesmo `vendas_1000000.csv`, uma transformação "aparar + remover duplicidades" num processo novo por cenário (pico do working set):

| Cenário | Pico antes da deduplicação | Pico no fim | Tempo |
| --- | --- | --- | --- |
| vendedor + produto (480 chaves, 999.520 duplicados), o do job `benchmark` | 249 MB | **1.358 MB** | 4,5 s |
| chave de 6 colunas quase única (1 duplicado) | 230 MB | **1.085 MB** | 4,8 s |

Por etapa, só a deduplicação, num processo novo que começa com cerca de 67 MB:

| Etapa (pico acumulado) | 480 chaves | Chave quase única |
| --- | --- | --- |
| Marcar mantidos e de qual registro cada um é duplicado | 314 MB | 862 MB |
| Gravar os mantidos | 331 MB | 963 MB |
| Carregar os registros originais dos duplicados | 634 MB | 963 MB |
| Montar as exclusões com os valores de entrada | 980 MB | 963 MB |
| Gravar as exclusões | 1.222 MB | 963 MB |

Na chave quase única, marcar só com `is_first_distinct` chega a 358 MB; a janela `first().over(chaves)`, que calcula de qual registro cada um é duplicado, sozinha chega a 762 MB. Selecionar só as colunas da chave antes de marcar não muda nada nesse cenário (802 MB), porque a chave já ocupa quase todas as colunas.

São duas causas, e as duas crescem com o volume:
- **Muitos duplicados:** as exclusões, com todas as colunas de entrada como texto (999.520 registros), são montadas inteiras em memória antes de gravar, cerca de 900 MB.
- **Muitas chaves distintas:** a janela calcula o registro mantido para todos os registros, com um grupo por chave, cerca de 700 MB com 1 milhão de grupos.

Com `WORKER_CONCURRENCY=2` e `WORKER_MEMORY=2g` (os valores do `.env.example`), duas deduplicações desse porte ao mesmo tempo somariam mais que o limite do contêiner. É uma conta a partir das medições acima, não um teste.

**Depois da ADR-031** (só a chave em memória, mantido procurado só para os descartados, gravação em lotes), mesmo ambiente e mesmo método, três execuções de cada:

| Cenário | Pico antes | Pico depois | Tempo antes | Tempo depois |
| --- | --- | --- | --- | --- |
| vendedor + produto (999.520 duplicados) | 1.358 MB | **513–536 MB** | 4,5–5,8 s | 6,5–6,8 s |
| chave de 6 colunas quase única (1 duplicado) | 1.085 MB | **627–636 MB** | 4,3–4,8 s | 4,5–4,7 s |

A reconciliação fechou em todas as execuções. O caso com muitos duplicados ficou mais lento porque as exclusões passaram a ser gravadas em grupos de 50 mil linhas, que o Parquet comprime mais devagar que um grupo único: 2,1 s contra 1,3 s para gravar as mesmas 999.520 linhas. Lotes de 250 mil devolviam o tempo (5,1–5,6 s), mas levavam o pico a cerca de 800 MB, e por isso ficaram os 50 mil das outras etapas. Os números do contêiner vêm do job `benchmark` da CI.

## Pendente

- Números do `benchmark_stack` na CI (acima), com o pico de memória por job (ADR-030).
- Mais repetições em um ambiente dedicado, para obter média e variação confiáveis.
- Transformações com 1 milhão de linhas e outras regras além da deduplicação; consultas dos dashboards com muitos widgets abertos ao mesmo tempo (cada widget é uma requisição, e a API atende 2 consultas por vez por processo, ADR-028).
- CSV perto do limite de 100 MB (o de 1 milhão tem 80 MB).
