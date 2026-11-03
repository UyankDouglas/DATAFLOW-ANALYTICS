# Decisões de arquitetura (ADRs)

Formato curto: contexto → decisão → consequências.

## ADR-001 — PostgreSQL como fonte da verdade, Celery apenas como transporte

**Contexto.** Jobs precisam de status durável, idempotência, retentativas e recuperação após quedas.
**Decisão.** O estado do job vive em `processing_jobs` (PostgreSQL). O Celery não usa backend de resultados (`task_ignore_result=True`). A tarefa recebe só o `job_id` e reivindica o job com `UPDATE … WHERE status='queued' OR (rodando AND heartbeat antigo)`.
**Consequências.** Reentregas são no-op; `acks_late` é seguro; o beat consegue reenfileirar jobs perdidos sem duplicar trabalho. Um índice único parcial garante no banco no máximo um job ativo por dataset.

## ADR-002 — Armazenamento de objetos (S3/MinIO) para arquivos, nunca no banco

**Decisão.** Originais e Parquet ficam em bucket privado, com chave determinística e aleatória (`workspaces/{ws}/uploads/{uuid}/original`, `…/versions/{job_id}/data.parquet`). O PostgreSQL guarda metadados, tamanho e SHA-256.
**Consequências.** Banco enxuto; versões imutáveis por chave; retentativas sobrescrevem o mesmo objeto (idempotente). Não existe URL pública: leitura sempre pela API.

## ADR-003 — Parquet + DuckDB para consultas

**Decisão.** Cada versão publicada é um Parquet (zstd). A API baixa o arquivo para um cache local identificado pelo id da versão, valida o checksum e consulta com DuckDB em memória.
**Consequências.** Versões imutáveis tornam o cache sempre consistente. DuckDB roda com `threads=2`, `memory_limit=512MB`, `enable_external_access=false`, `allowed_directories=[cache]` e `lock_configuration=true`. Identificadores são validados contra o esquema da versão e citados; valores são parâmetros. Não há SQL vindo do usuário. *Alternativa considerada:* extensão `httpfs` lendo direto do S3 — descartada na Fase 1 por exigir download de extensão em runtime e credenciais dentro do DuckDB.

## ADR-004 — Tokenização com `csv` + conversão vetorizada com Polars

**Contexto.** Requisito: "não interpretar silenciosamente dados ambíguos" e "não descartar dados incorretos silenciosamente".
**Teste realizado (Polars 2.1).** Com `scan_csv` e esquema fixo, uma linha com campos **a menos** é preenchida com nulos (ou strings vazias com `empty_string_is_null=False`) — indistinguível de campos vazios legítimos. Campos **a mais** são truncados com `truncate_ragged_lines=True`.
**Decisão.** O módulo `csv` da biblioteca padrão faz a tokenização em streaming (modo estrito, limite por campo), detectando por registro: linha vazia, campos a menos/a mais e aspas malformadas. Cada lote de 50 mil registros vira um `DataFrame` Polars (transposição em C via `zip`) e toda conversão de tipos, nulos e validação é vetorizada no Polars. Arrow/PyArrow grava o Parquet incrementalmente.
**Consequências.** Rejeições estruturais rastreáveis por registro e linha. Medido: ~0,5 s de leitura e ~0,9 s de pipeline total para 100 mil linhas (ver `benchmark.md`). Para arquivos muito grandes e sabidamente limpos, um caminho rápido com o leitor nativo do Polars está no roadmap (Fase 6).

## ADR-005 — Decimais nunca em ponto flutuante

**Decisão.** Colunas decimais usam `Decimal(38, escala)` no Polars e `decimal128` no Parquet. A escala vem da inferência e é editável. Valores com mais casas que a escala são **rejeitados** (`casas_decimais_excedidas`), não arredondados. Na API, decimais trafegam como **texto** e o frontend formata sem converter para `number`.
**Consequências.** Precisão preservada fim a fim; nenhuma coluna recebe formato monetário automaticamente.

## ADR-006 — MinIO via imagem mantida pela Chainguard

**Contexto.** O MinIO Community Edition entrou em modo de manutenção em dez/2025 e o repositório foi arquivado em 2026. As imagens `minio/minio` não estão mais disponíveis no Docker Hub (verificado em 29/10/2026: o registro responde 401 para o repositório) e o binário oficial para Windows retorna `410 Gone`.
**Decisão.** Manter MinIO (requisito do projeto) usando `cgr.dev/chainguard/minio`, build gratuito e atualizado (imagem de 28/10/2026). A imagem é configurável por `MINIO_IMAGE` e deve ser fixada por digest em produção. Como ela é distroless e roda como UID 65532, o Compose usa um serviço `minio-perms` para ajustar o volume e um `storage-setup` (Python/boto3) que aguarda o S3 responder e cria o bucket.
**Consequências.** O backend fala apenas o protocolo S3 (boto3, path-style), então trocar por SeaweedFS, Garage, RustFS ou um S3 gerenciado é mudança de configuração, não de código.

## ADR-007 — SQLAlchemy síncrono compartilhado

**Decisão.** Sessões síncronas (psycopg 3). Endpoints síncronos rodam no threadpool do FastAPI; só o upload é `async`, para consumir o corpo em streaming, e delega banco/S3 para threads.
**Consequências.** O worker Celery (síncrono) reutiliza exatamente os mesmos serviços e modelos, sem duas pilhas de acesso a dados.

## ADR-008 — Upload como corpo binário em streaming (não multipart)

**Decisão.** `POST /datasets/upload` recebe o arquivo como `application/octet-stream`, nome no cabeçalho `X-File-Name`. O servidor grava em disco em blocos enquanto calcula SHA-256, valida UTF-8 incrementalmente, detecta assinaturas binárias e aborta assim que o limite é excedido. O Caddy também limita o corpo.
**Consequências.** Nada é lido inteiro em memória; o limite é aplicado durante o recebimento (com multipart, o Starlette só valida após receber tudo). O frontend usa `XMLHttpRequest` para ter progresso de envio real.

## ADR-009 — Sessões de servidor + CSRF double-submit assinado

**Decisão.** Cookie `df_session` (HttpOnly, SameSite=Lax, Secure em produção) com token aleatório; o banco guarda só o SHA-256. CSRF: cookie legível `df_csrf` + cabeçalho `X-CSRF-Token` iguais, e o token deve ser `HMAC(secret, hash_da_sessão)` (ou um token anônimo assinado antes do login). O middleware também recusa `Origin` fora da allowlist.
**Consequências.** Logout e troca de senha revogam sessões no servidor; um token CSRF roubado não serve para outra sessão.

## ADR-010 — Progresso real por bytes lidos

**Decisão.** O worker atualiza `bytes_processed`, `rows_processed` e `heartbeat_at` a cada lote. O percentual exibido é bytes lidos ÷ tamanho do arquivo na etapa de processamento. Nas demais etapas (fila, validação, salvamento) o indicador é indeterminado. O total exato de registros só é informado ao final.
**Consequências.** Nenhum percentual simulado; uma única passada pelo arquivo.

## ADR-011 — Versões das dependências

Versões estáveis verificadas em 29/10/2026. Escolhas conscientes de não usar o "latest":

| Pacote | Escolhido | Disponível | Motivo |
| --- | --- | --- | --- |
| TypeScript | 5.9.3 | 7.0.2 | typescript-eslint 8.72 suporta `<6.1`; TS 7 (port nativo) ainda não expõe a API usada pelo lint. |
| React Router | 7.18.5 | 8.5.1 | v7 é estável e amplamente documentada; migração para v8 fica para quando o projeto estabilizar. |
| TanStack Table | 8.21.3 | 9.3.1 | v9 muda a API de features; v8 segue mantida. |
| DuckDB | 1.5.6 | 2.0.0 | 2.0.0 ainda sem patch release; 1.5.x é a linha estável madura. |
| Polars | 2.1.0 | 2.1.0 | linha atual; APIs usadas verificadas nesta versão. |

## ADR-012 — Rate limiting falha aberto

**Decisão.** Se o Redis estiver indisponível, o limitador registra aviso e permite a requisição.
**Consequências.** Indisponibilidade do Redis não derruba login; em contrapartida, durante a falha não há limitação. O healthcheck `/health/ready` sinaliza o problema.

## ADR-013 — Testes: SQLite local, PostgreSQL na CI

**Decisão.** A mesma suíte roda com SQLite (rápida, sem infraestrutura) ou com PostgreSQL real via `TEST_DATABASE_URL` — a CI usa PostgreSQL e aplica as migrations (upgrade → check → downgrade → upgrade). S3 (moto) e Redis (fakeredis) são simulados **apenas nos testes**.
**Consequências.** Tipos portáveis (`Uuid`, `JSON` com variante `JSONB`, timestamps UTC por `TypeDecorator`). Comportamentos específicos do PostgreSQL (FKs circulares, `FOR UPDATE SKIP LOCKED`) são exercitados na CI.

## ADR-014 — XLSX com openpyxl somente leitura, sem executar fórmulas

**Contexto.** Planilhas são ZIP com XML: podem ser bombas de descompressão, trazer macros, estar criptografadas ou ter fórmulas cujo resultado depende de recálculo.
**Decisão.** Verificar o contêiner antes de abrir (assinatura, criptografia, entradas, tamanho e taxa de descompressão, `[Content_Types].xml`, macros), no upload e de novo no worker. Abrir com openpyxl em `read_only=True` e `defusedxml` ativo, duas vezes (valores salvos e fórmulas), para distinguir fórmula com valor salvo (entra pelo valor) de fórmula sem valor (registro rejeitado com `formula_sem_valor`). Nenhuma fórmula é calculada e nenhuma macro é lida. Dimensões declaradas são ignoradas; o cabeçalho é a primeira linha "larga" das 50 primeiras, ajustável pelo usuário.
**Consequências.** Arquivos gerados por bibliotecas que não calculam fórmulas têm essas linhas rejeitadas — de forma explícita, nunca com valor inventado. A leitura dupla custa tempo — cerca de 40 vezes mais lento que CSV na medição local (ver `docs/benchmark.md`); por isso o limite de XLSX (25 MB) é menor que o de CSV e o progresso de XLSX mostra só registros processados.

## ADR-015 — Transformações como regras declarativas de uma lista fechada

**Contexto.** O usuário precisa limpar e derivar dados sem que o sistema execute código, SQL ou expressões enviadas por ele.
**Decisão.** Cada regra é um objeto JSON validado por um modelo Pydantic de uma união discriminada (`operation`), com `extra="forbid"`. Antes de qualquer execução, `plan_rules` percorre as regras na ordem e calcula o esquema após cada uma, recusando coluna inexistente, tipo incompatível, formato fora da allowlist, nome inválido ou duplicado e literal que não converte — com a posição da regra no erro. Colunas derivadas só aceitam operações enumeradas (aritmética, concatenação, parte de data, diferença de dias) com operandos que são coluna ou valor fixo. A execução usa expressões do Polars montadas pelo backend.
**Consequências.** Não há como injetar código; a mesma validação roda ao salvar o conjunto, na prévia e no worker (contra a versão de origem escolhida). O frontend simula o esquema só para oferecer as colunas certas; quem decide é o servidor.

## ADR-016 — Categorias de exclusão mutuamente exclusivas

**Contexto.** Com filtros e deduplicação, "rejeitado" deixou de descrever tudo o que não entra na versão, e a reconciliação precisa continuar fechando sem contagem dupla.
**Decisão.** Quatro categorias: válido, rejeitado (problema de dado), filtrado (escolha do usuário) e duplicado (removido pela deduplicação). Um registro sai na primeira regra que o exclui e é registrado uma vez no `rejected.parquet`, com categoria, motivo, regra, coluna, detalhe e valores de entrada. `recebidos = válidos + rejeitados + filtrados + duplicados`; política de duplicados explícita (`removidos_dos_validos` ou `nao_aplicada`). A deduplicação precisa ser a última regra ativa e roda sobre o resultado inteiro da primeira passada, não por lote.
**Consequências.** Contagens comparáveis entre importação e transformação; a análise de duplicidades (DuckDB) e o job (Polars) usam a mesma semântica — nulos iguais entre si — e a suíte confere que contam o mesmo. A deduplicação carrega a chave e o número do registro de toda a versão em memória; para volumes muito acima do benchmark será preciso particionar por hash da chave.

## ADR-017 — Reprocessamento por jobs versão → versão, com cópia das regras

**Contexto.** Versões publicadas são imutáveis, e cada nova versão precisa dizer de onde veio e o que foi aplicado.
**Decisão.** Transformação é um job próprio (`kind = "transform"`) com a mesma máquina de estados, idempotência, cancelamento, retentativas e publicação atômica da importação. A entrada é o Parquet de uma versão publicada (SHA-256 conferido); a saída é uma nova versão com `parent_version_id`, `transformation_set_id` e, em `transformations`, a origem, o conjunto (nome e revisão) e a lista de regras aplicadas. O job guarda essa cópia na criação; conjuntos têm revisão incrementada a cada edição.
**Consequências.** Editar ou excluir um conjunto não altera versões já geradas (a FK vira nula, a cópia permanece). Qualquer versão pode ser origem, formando cadeias como v1 → v2 → v3. A tarefa Celery continua `imports.run` para não perder mensagens em trânsito; o worker despacha pelo tipo do job.

## ADR-018 — Aritmética decimal com arredondamento meio-para-par

**Decisão.** Colunas derivadas aritméticas operam em `Decimal(38, escala)` com escala de trabalho maior que a de saída; o ajuste para a escala pedida segue o cast do Polars, que arredonda meio-para-par (1,005 → 1,00; 1,015 → 1,02). Conversões de tipo e de escala configuradas pelo usuário continuam sem arredondar: se perder casas, o registro é rejeitado (ADR-005). Divisão por zero rejeita o registro com `divisao_por_zero`.
**Consequências.** Resultado determinístico e sem viés estatístico de arredondamento; difere do arredondamento "meio para cima" de planilhas, o que está documentado em `docs/data-pipeline.md`.

## ADR-019 — Relatório de qualidade persistido por versão, só com agregados

**Contexto.** O prompt mestre pede `QualityReport` e `QualityIssue`, uma nota de 0 a 100 com fórmula reproduzível e uma tabela de inconsistências consultável.
**Decisão.** Um relatório por versão (`UNIQUE(version_id)`), calculado com DuckDB sobre os Parquet da versão. O worker calcula logo depois de publicar; versões antigas são calculadas sob demanda. O relatório guarda contagens, componentes, perfil das colunas e grupos de exclusão (categoria, motivo, coluna, regra, contagem e um registro de exemplo). Valores de texto dos dados ficam fora do PostgreSQL: frequência de valores e valor original de cada inconsistência são lidos do Parquet na hora, com a checagem de workspace. A fórmula tem versão (`FORMULA_VERSION`) e está em `docs/quality.md`.
**Consequências.** A tabela de inconsistências não duplica o `rejected.parquet` no banco e serve qualquer volume com paginação no servidor. Uma falha no cálculo vira aviso no job, sem invalidar a versão. Mudar a fórmula exige recalcular os relatórios para que fiquem comparáveis.

## ADR-020 — Data Explorer com filtros tipados, busca literal e tempo-limite

**Decisão.** `POST /datasets/{id}/rows/query` recebe filtros com os mesmos operadores e a mesma validação por tipo das regras de filtro das transformações (ADR-015), combinados por E ou OU, mais uma busca textual. Colunas e ordenação são validadas contra o esquema da versão; valores sempre vão como parâmetros do DuckDB (`list_contains` para listas). A busca usa `contains(lower(coluna), $termo)`, então `%` e `_` são texto literal, e percorre só as colunas de texto. Limites: 20 filtros, 50 valores por lista, busca de 100 caracteres, página de no máximo 200 registros e 10 s por consulta, com `interrupt()` do DuckDB acionado por um timer.
**Consequências.** O filtro do explorer e o da transformação têm a mesma semântica. A contagem filtrada custa uma segunda consulta (`count(*)`); sem filtros, usa a contagem da versão. O download do resultado filtrado fica para as exportações da Fase 5, que precisam de job assíncrono, expiração e proteção contra formula injection.

## ADR-021 — Consultas analíticas com vocabulário fechado, recalculadas a cada abertura

**Decisão.** KPIs e gráficos vêm de `POST /datasets/{id}/analytics` e `POST /dashboards/{id}/query`. Ambos recebem uma consulta de vocabulário fechado: medidas `{agregação, coluna}` de uma lista por tipo de coluna, dimensão com granularidade de data, filtros tipados do explorer (ADR-020), ordenação, limite e comparação entre períodos. A consulta é validada contra o esquema da versão e montada como SQL do DuckDB pelo backend (`analytics/aggregate.py`), com valores parametrizados. Os resultados não são guardados: versões são imutáveis e o Parquet já fica em cache local, então recalcular custa dezenas de milissegundos com 100 mil registros. Grupos de categoria além do limite vão para "Outros", calculado sobre os registros restantes. Séries temporais nunca são cortadas e, acima de 1.000 pontos, pedem uma granularidade maior. A comparação calcula os dois períodos numa só leitura, com `FILTER`.
**Consequências.** Não há cache de resultados para invalidar nem número velho na tela. Um dashboard que acompanha a versão atual mostra os dados novos assim que ela é publicada. O custo vai para cada abertura: com arquivos muito maiores pode ser preciso materializar agregados, o que fica registrado como pendência de medição. Decimais não servem como dimensão (seriam um grupo por valor); a faixa de valores é um filtro. O resultado diz o tipo de cada medida, nunca o significado: nada é formatado como moeda.

## ADR-022 — Dashboards guardam definições, com versão fixa ou atual e revalidação ao salvar

**Decisão.** `Dashboard` guarda dataset, versão opcional, filtros gerais e widgets. Versão nula significa acompanhar a atual. A versão fixada referencia `dataset_versions` sem `ON DELETE`, para não sumir por baixo de um dashboard. `DashboardWidget` guarda tipo, tamanho, posição e a consulta validada pelo mesmo modelo da API analítica. Cada `PATCH` revalida o dashboard inteiro contra a versão resultante, inclusive as regras por tipo de gráfico (pizza só com contagem ou soma, KPI sem dimensão). Os widgets mantêm o `id` ao serem reorganizados; posições provisórias evitam colisão com a restrição única durante a troca de ordem. Na consulta, os filtros salvos e os da tela entram como grupos separados, combinados com E, cada um com o próprio E/OU. Criar e editar exigem `dashboards:manage`, permissão nova dada a Analista e Administrador; abrir e filtrar ficam com `datasets:view`.
**Consequências.** Mudar o esquema da versão atual (renomear uma coluna) não quebra o dashboard inteiro: só o widget afetado responde `widget_incompatible`, e salvar exige corrigi-lo ou fixar uma versão compatível. Duas pessoas editando o mesmo dashboard: vale a última gravação (sem controle de concorrência nesta fase). A exclusão controlada de versões (Fase 5) precisa tratar as versões fixadas por dashboards.
