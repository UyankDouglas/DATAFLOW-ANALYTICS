# PROGRESS — DataFlow Analytics

Documento de retomada. Atualizado em **03/11/2026**.

## Fases

| Fase | Status |
| --- | --- |
| 1 — Fundação e primeiro dataset | ✅ Concluída e validada na CI com a infraestrutura real, nos Compose de desenvolvimento e de produção |
| 2 — Motor ETL (XLSX, transformações, deduplicação, reprocessamento) | ✅ Concluída e validada na CI com a infraestrutura real ([PR #1](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/pull/1), branch `fase-2-motor-etl`, ainda **não mesclado** na `main`) |
| 3 — Qualidade e Data Explorer completo | ✅ Implementada e validada localmente (sem Docker), na branch `fase-3-qualidade` (criada a partir da `fase-2-motor-etl`), ainda **sem commit**. Falta a validação na CI |
| 4 — Business Intelligence (dashboards) | ⏳ Próxima |
| 5 — Relatórios, exportações e administração | Pendente |
| 6 — Qualidade e produção | Pendente |

## Fase 1 — concluído

- [x] Repositório, backend (uv) e frontend (pnpm) — estrutura conforme o prompt mestre.
- [x] Docker Compose (dev e prod) com PostgreSQL 17, Redis 8.8, MinIO (Chainguard), Mailpit, migrate, storage-setup, API, worker, beat e Caddy; healthchecks e variáveis de ambiente.
- [x] SQLAlchemy 2.1 + Alembic: `users`, `user_sessions`, `password_reset_tokens`, `workspaces`, `workspace_members`, `datasets`, `dataset_columns`, `uploads`, `processing_jobs`, `dataset_versions`, `audit_logs` (FKs, índices, CHECKs, índice único parcial de job ativo).
- [x] Autenticação: cadastro, login, logout, me, recuperação/redefinição de senha (e-mail via worker), Argon2id, sessões HttpOnly no servidor, CSRF assinado, rate limiting, RBAC, isolamento por workspace, troca de workspace, auditoria.
- [x] Layout: sidebar recolhível, topbar (workspace, notificações reais, tema, usuário), tema escuro padrão + claro, responsivo, telas "Em desenvolvimento" para módulos futuros.
- [x] Upload CSV em streaming para o MinIO com validação de conteúdo, limites e metadados.
- [x] Pré-visualização: 20 linhas, tipos inferidos, nulos, distintos, contagem exata/estimada, avisos; opções de leitura editáveis.
- [x] Mapeamento de colunas (nome, tipo, formato, escala) salvo e reutilizável; bloqueio de duplicados; confirmação de datas ambíguas.
- [x] Worker Celery: pipeline em lotes → Parquet (válidos + rejeitados), reconciliação, progresso real, cancelamento cooperativo, retentativas, idempotência, recuperação de jobs, publicação atômica de versão.
- [x] Tela de acompanhamento do job, histórico de processamentos, detalhe do dataset, Data Explorer paginado e ordenado no servidor (DuckDB).
- [x] Gerador reproduzível de dados fictícios (vendas, atendimentos, qualidade) — 1k/10k/100k linhas.
- [x] Testes: backend (Pytest), frontend (Vitest), E2E (Playwright); CI no GitHub Actions.
- [x] Documentação: README, `docs/architecture.md`, `decisions.md`, `security.md`, `data-pipeline.md`, `deploy.md`, `benchmark.md`.

## Fase 2 — concluído

- [x] **XLSX** (`processing/xlsx.py`): upload até 25 MB com verificação do contêiner antes de abrir — criptografia, XLS legado, ZIP inválido, entradas demais, limite de descompressão e taxa de compressão (bomba), macros — repetida no worker. openpyxl somente leitura com `defusedxml`; fórmulas nunca calculadas (sem valor salvo → `formula_sem_valor`), células de erro → `erro_na_celula`. Seleção de aba, linha do cabeçalho detectada (pula títulos) ou escolhida, intervalo de dados, linhas vazias finais ignoradas com aviso, outra aba como dataset independente (cópia própria no S3). Dimensionamento de abas sem `<dimension>` corrigido (o openpyxl lia a planilha inteira para abrir).
- [x] **Mapeamento:** coluna obrigatória (`campo_obrigatorio`) e valor para vazios (formato canônico, validado contra o tipo antes de processar).
- [x] **Transformações** (`processing/transforms.py`): 12 operações de lista fechada, validadas por Pydantic (`extra="forbid"`) e planejadas contra o esquema (`plan_rules`), sem `eval` nem código do usuário; colunas derivadas aritméticas em decimal com arredondamento meio-para-par e divisão por zero rejeitada.
- [x] **Conjuntos de regras** (`transformation_sets`, `transformation_rules`) com revisão; CRUD na API com RBAC (`transformations:manage`) e auditoria.
- [x] **Prévia** sobre 200 registros (sem gravar), **análise de duplicidades** na versão inteira (DuckDB) e **deduplicação** por todas ou algumas colunas, mantendo primeiro ou último, como segunda passada.
- [x] **Jobs de transformação** (versão → versão) com a mesma máquina de estados, idempotência, cancelamento, retentativas e publicação atômica; regras congeladas no job; progresso por registros.
- [x] **Reconciliação** `recebidos = válidos + rejeitados + filtrados + duplicados`, categorias mutuamente exclusivas, `rejected.parquet` com categoria, regra e registro mantido (`__df_duplicate_of`).
- [x] **Linhagem:** `parent_version_id`, `transformation_set_id`, origem, conjunto, revisão e regras em `transformations`; contagens de filtrados e duplicados por versão e por job.
- [x] **Migration 0002** aditiva (tabelas novas, colunas anuláveis ou com padrão); upgrade/downgrade verificados no SQLite e SQL renderizado para PostgreSQL.
- [x] **Interface:** importação aceita XLSX; pré-visualização com aba, linha do cabeçalho e outras abas; mapeamento com "Obrigatória" e "Se vazio"; tela **Transformações** (saiu de "Em desenvolvimento") com editor de regras, simulação do esquema no cliente, prévia, duplicidades, salvar e aplicar; job e dataset mostram tipo, origem, filtrados, duplicados, regras aplicadas e categoria de cada exclusão.
- [x] **Amostras:** `scripts/generate_samples.py --xlsx` (determinístico; mesmas vendas e atendimentos dos CSV, aba de fórmulas sem valor); `samples/vendas_atendimentos_1000.xlsx` versionado.
- [x] **Benchmark** `app/scripts/benchmark_etl.py` (XLSX + transformação + conferência DuckDB × pipeline).
- [x] **Documentação:** README, `docs/data-pipeline.md` (reescrito), ADR-014 a ADR-018, `security.md`, `architecture.md`, `benchmark.md`, `samples/README.md`; capturas 09 e 10 e as demais regeneradas.
- [x] **Correções encontradas no caminho:** a limpeza dos testes deixava as chaves estrangeiras do SQLite desligadas depois do primeiro teste (PRAGMA ignorado dentro de transação); a conversão de tipos recalculava expressões e ficou ~2× mais lenta na Fase 2 até ser reestruturada em etapas (medido contra o código da Fase 1 na mesma máquina); a estimativa de registros da prévia de XLSX ignorava a dimensão da aba.

## Fase 3 — concluído

- [x] **Relatório de qualidade por versão** (`analytics/quality.py`, `services/quality_service.py`, tabelas `quality_reports` e `quality_issues`, migration 0003 aditiva): calculado pelo worker logo depois de publicar cada versão (falha vira aviso, sem desfazer a versão) ou sob demanda por quem tem `datasets:process`; recalcular substitui o relatório.
- [x] **Nota de 0 a 100** com fórmula versionada e documentada em `docs/quality.md`: `100 × (0,4 validade + 0,4 completude + 0,2 unicidade)`, com casos-limite (sem registros → nula; nenhum válido → 0).
- [x] **Indicadores** do prompt mestre: total, válidos, rejeitados, duplicados (removidos + restantes), valores nulos, colunas com inconsistências, completude, regras violadas e violações.
- [x] **Perfil das colunas** (completude, nulos, distintos, mínimo e máximo de números e datas, exclusões atribuídas) e **distribuição de nulos** por registro; frequência de valores sob demanda, lida do Parquet.
- [x] **Tabela de inconsistências** a partir do `rejected.parquet`: registro, linha, coluna, valor original, tipo do problema, regra violada (com o nome da operação) e tratamento aplicado; filtros por categoria, motivo e coluna; paginação no servidor; compatível com versões da Fase 1.
- [x] **Comparação entre versões** (nota e componentes) e nota de cada versão no detalhe do dataset.
- [x] **Data Explorer completo** (`POST /datasets/{id}/rows/query`): filtros tipados com os operadores das regras de filtro (E/OU), busca literal nas colunas de texto, seleção e ordem de colunas, contagem filtrada, ordenação e paginação no servidor; limites de 20 filtros, 100 caracteres de busca, 200 registros por página e 10 s por consulta (`interrupt` do DuckDB).
- [x] **Interface:** tela Qualidade dos Dados (saiu de "Em desenvolvimento") com gráficos Recharts, duplicidades por chave e inconsistências; explorer com busca, painel de filtros e seletor de colunas; atalho e nota no detalhe do dataset. O painel de duplicidades virou componente compartilhado, e a análise (só leitura) passou a ser liberada para Visualizador.
- [x] **Benchmark:** `benchmark_pipeline` passou a medir o relatório de qualidade e uma consulta filtrada.
- [x] **Documentação:** `docs/quality.md` (novo), ADR-019 e ADR-020, `data-pipeline.md`, `security.md`, `architecture.md`, `benchmark.md`, README; capturas 11 e 12 e as demais regeneradas.
- **Fora desta fase, de propósito:** download do resultado filtrado do explorer (chega com as exportações protegidas da Fase 5).

## Testes executados na CI — Fase 2 (03/11/2026, commit `2532df8`, [execução 41649777153](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41649777153), PR #1)

| Verificação | Resultado |
| --- | --- |
| Backend contra **PostgreSQL 17 real** | **120 passed**, cobertura de 88% |
| Alembic `upgrade` → `check` → `downgrade` → `upgrade` no PostgreSQL | OK; `check`: "No new upgrade operations detected" |
| Ruff e mypy estrito | sem problemas (74 arquivos) |
| Frontend: formatação, lint, tipos, Vitest, build | OK, **40 passed** |
| E2E em desenvolvimento, com Celery, MinIO e Redis reais | **9 passed**, 1 ignorado (capturas de tela) |
| E2E em produção, em HTTPS | **8 passed**, 2 ignorados (e-mail e capturas de tela) |
| CSV de 100 mil linhas pela interface | job de 815 ms em desenvolvimento e 841 ms em produção (122.699 e 118.906 registros/s); pico de RSS do worker 345 e 338 MB (pico do processo inteiro, depois de outros E2E — inclusive XLSX — no mesmo worker) |

## Testes executados na CI (30/10/2026, commit `a11e2fd`, [execução 41126313886](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41126313886))

| Verificação | Resultado |
| --- | --- |
| Backend contra **PostgreSQL 17 real** | **64 passed**, cobertura de 87% |
| Alembic: `upgrade` → `check` → `downgrade` → `upgrade` no PostgreSQL | OK, sem divergência entre modelos e migration |
| Ruff e mypy estrito | sem problemas |
| Frontend: formatação, lint, tipos, Vitest, build | OK, **22 passed** |
| Compose de **desenvolvimento**, a partir do `.env.example` | todos os serviços saudáveis |
| E2E em desenvolvimento, com Celery e MinIO reais | **6 passed**, 1 ignorado (capturas de tela, só sob demanda). Inclui 100 mil linhas (8 MB) pela interface, a recusa de corpos acima de 2 MB fora da rota de upload e a recuperação de senha com o e-mail entregue ao Mailpit por SMTP |
| Compose de **produção**, a partir do `.env.example`, em HTTPS com a CA interna do Caddy | todos os serviços saudáveis; `/health/ready` OK |
| Borda de produção | HTTP responde 308 para HTTPS; cookies `Secure`; portas 5432, 6379, 8000, 8025, 8080, 9000 e 9001 fechadas; Redis responde `NOAUTH` sem senha |
| E2E em produção | **5 passed**, 2 ignorados (e-mail, pois produção não tem Mailpit, e capturas de tela) |
| Fluxo completo medido | job de 100 mil linhas entre 741 ms e 1.046 ms em 3 execuções; detalhes em `docs/benchmark.md` |

## Testes executados localmente — Fase 3 (03/11/2026, Windows 10, sem Docker)

| Comando | Resultado |
| --- | --- |
| `cd backend && uv run pytest` | **139 passed** (SQLite + moto/S3 + fakeredis) |
| `uv run ruff format --check . && uv run ruff check .` / `uv run mypy app` | sem problemas (79 arquivos no mypy) |
| Alembic `upgrade head` + `check` no SQLite; `upgrade 0002:0003 --sql` para PostgreSQL | OK (o `check` só aponta as FKs por `ALTER` que o SQLite não cria; nenhuma da 0003) |
| `cd apps/web && pnpm test` | **47 passed** (14 arquivos); lint, typecheck, format e build OK |
| `cd e2e && E2E_BASE_URL=http://localhost:5173 pnpm test quality full-flow etl` | **7 passed** (`quality.spec.ts` ×2 novos, mais os da Fase 2 e o fluxo completo) |
| `CAPTURE_SCREENSHOTS=1 … pnpm test screenshots` | 12 capturas em `docs/screenshots/` |
| Verificação manual no navegador | relatório calculado pelo worker, gráficos, inconsistências, explorer com busca/filtro/colunas; sem rolagem horizontal em 375 px nas duas telas |
| `uv run python -m app.scripts.benchmark_pipeline …100000.csv` | relatório de qualidade em 0,19–0,28 s; consulta filtrada com contagem em 0,11–0,12 s |

**Ainda não validado (depende da CI):** suíte contra PostgreSQL com a migration 0003, `alembic check` no PostgreSQL e os E2E da Fase 3 com Celery, MinIO e Redis reais.

## Testes executados localmente — Fase 2 (03/11/2026, Windows 10, sem Docker)

| Comando | Resultado |
| --- | --- |
| `cd backend && uv run pytest` | **120 passed** (SQLite + moto/S3 + fakeredis), com chaves estrangeiras realmente ativas no SQLite |
| `uv run ruff format --check . && uv run ruff check .` | sem problemas |
| `uv run mypy app` (strict, com `types-openpyxl`) | sem problemas em 74 arquivos |
| Alembic `upgrade head` + `check` no SQLite | OK; o `check` aponta só as FKs adicionadas por `ALTER`, que o SQLite não suporta (a migration as pula no SQLite) |
| Alembic `upgrade 0001:0002 --sql` (PostgreSQL offline) | `CREATE TABLE`, `ADD COLUMN`, FKs e troca do CHECK de `kind` conferidos |
| `cd apps/web && pnpm test` | **40 passed** (10 arquivos) |
| `pnpm lint`, `pnpm typecheck`, `pnpm format:check`, `pnpm build` | OK |
| `cd e2e && E2E_BASE_URL=http://localhost:5173 pnpm test` | **7 passed** (`etl.spec.ts` ×3, `full-flow.spec.ts` ×2, `isolation.spec.ts`, `large-file.spec.ts`); recuperação de senha não roda sem o Mailpit |
| `CAPTURE_SCREENSHOTS=1 … pnpm test screenshots` | 10 capturas em `docs/screenshots/` |
| Verificação manual no navegador (Vite + API local) | upload XLSX, aba/cabeçalho, obrigatória/se vazio, importação, conjunto de regras, prévia, duplicidades, aplicação (v2 com 1.000 = 415 + 0 + 73 + 512), linhagem no dataset, outra aba como dataset, layout em 375 px sem rolagem horizontal |
| `uv run python -m app.scripts.benchmark_etl …100000.xlsx` | ver `docs/benchmark.md` |

O E2E e a verificação manual usaram o mesmo harness da Fase 1, **fora do repositório**: frontend e API reais, com SQLite, moto, fakeredis e o `run_job` do worker numa thread no lugar de PostgreSQL, MinIO, Redis e Celery. O harness tem rate limit de cadastro real (10 por hora), então foi reiniciado entre execuções longas.

**Ainda não validado (depende da CI ou de Docker):** suíte do backend contra PostgreSQL 17 e `alembic check` no PostgreSQL; migration 0002 aplicada sobre um banco com dados da Fase 1; os E2E da Fase 2 com Celery, MinIO e Redis reais, em desenvolvimento e em produção; XLSX e transformação medidos no fluxo completo.

## Testes executados localmente — Fase 1 (29/10/2026, Windows 10, sem Docker)

| Comando | Resultado |
| --- | --- |
| `cd backend && uv run pytest` | **58 passed** (SQLite + moto/S3 + fakeredis) |
| `uv run ruff format --check . && uv run ruff check .` | sem problemas |
| `uv run mypy app` (strict) | sem problemas em 67 arquivos |
| Alembic `upgrade head` → `downgrade base` no SQLite | OK |
| Alembic `upgrade head --sql` (renderização PostgreSQL offline) | OK (FKs circulares via `ALTER`, índice único parcial) |
| `cd apps/web && pnpm test` | **22 passed** (6 arquivos) |
| `pnpm lint`, `pnpm typecheck`, `pnpm format:check`, `pnpm build` | OK (bundle dividido por rota) |
| `cd e2e && E2E_BASE_URL=http://localhost:5173 pnpm test` | **3 passed** — ver observação abaixo |
| `uv run python -m app.scripts.benchmark_pipeline …100000.csv` | ver `docs/benchmark.md` |
| Validação YAML de `docker-compose*.yml` e `ci.yml` | OK (sintaxe) |

**Observação sobre o E2E local:** sem Docker na máquina, o E2E rodou contra o frontend real (Vite) e a API real, com um harness temporário **fora do repositório** que substituiu apenas a infraestrutura: SQLite no lugar do PostgreSQL, moto (S3 em memória) no lugar do MinIO, fakeredis no lugar do Redis e o `run_import_job` do worker numa thread no lugar do Celery. Todo o código de domínio executado é o mesmo da produção. As capturas de `docs/screenshots/` foram geradas nesse mesmo fluxo.

## Fora do alcance da CI

Não bloqueiam a Fase 3, mas ainda não foram exercitados em nenhum ambiente, porque dependem de uma implantação real:

- Certificado público (Let's Encrypt) com domínio real; a CI usa a CA interna do Caddy.
- SMTP real com TLS e autenticação; a CI usa o Mailpit, sem TLS.
- Atualização de uma instalação existente e restauração de backup.

O Docker Desktop foi instalado na máquina de desenvolvimento, mas não inicia (`Docker Desktop is unable to start`, em 30/10/2026). Enquanto isso, o ambiente em contêineres só roda na CI.

## Arquivos relevantes

| Área | Arquivos |
| --- | --- |
| Configuração | `backend/app/core/config.py`, `.env.example` |
| Modelos / migrations | `backend/app/models/*`, `backend/migrations/versions/20261029_0001_initial_schema.py`, `20261103_0002_transformacoes_e_xlsx.py` |
| Autenticação | `backend/app/services/auth_service.py`, `backend/app/api/routes/auth.py`, `backend/app/api/deps.py`, `backend/app/api/middleware.py` |
| Upload / preview / importação | `backend/app/services/{upload,preview,import}_service.py` |
| Transformações | `backend/app/services/transformation_service.py`, `backend/app/api/routes/transformations.py`, `backend/app/schemas/transformation.py` |
| Pipeline | `backend/app/processing/{inspection,inference,reader,xlsx,convert,transforms,pipeline,types}.py` |
| Worker | `backend/app/services/job_runner.py`, `backend/app/tasks/*` |
| Consultas e qualidade | `backend/app/analytics/{query,quality,cache}.py`, `backend/app/services/quality_service.py`, `backend/app/api/routes/quality.py` |
| Frontend | `apps/web/src/app/router.tsx`, `apps/web/src/pages/**`, `apps/web/src/features/**` (inclui `transformations/`), `apps/web/src/services/api-client.ts` |
| Infra | `docker-compose.yml`, `docker-compose.prod.yml`, `docker/**`, `.github/workflows/ci.yml` |
| Dados | `scripts/generate_samples.py`, `samples/` |

## Decisões que não podem se perder

- MinIO via `cgr.dev/chainguard/minio` (imagem oficial indisponível; ADR-006).
- Tokenização com `csv` + conversão com Polars (Polars preenche campos ausentes em silêncio; ADR-004).
- Decimais como `Decimal(38, escala)`, trafegando como texto na API; escala excedida rejeita (ADR-005); colunas derivadas arredondam meio-para-par (ADR-018).
- Estado de job no PostgreSQL; Celery só transporte; reivindicação condicional (ADR-001). A tarefa continua `imports.run` também para transformações (ADR-017).
- Upload por corpo binário em streaming, não multipart (ADR-008).
- TypeScript 5.9, React Router 7, TanStack Table 8, DuckDB 1.5 por compatibilidade (ADR-011).
- XLSX lido duas vezes (valores e fórmulas), sem calcular nada (ADR-014); o dimensionamento das abas do openpyxl é substituído em `processing/xlsx.py`.
- Regras de transformação só de lista fechada, validadas contra o esquema da versão (ADR-015).
- Categorias de exclusão mutuamente exclusivas; deduplicação como última regra e segunda passada (ADR-016).
- Relatório de qualidade persistido por versão, só com agregados; valores de texto lidos do Parquet sob demanda (ADR-019). Mudar a fórmula exige incrementar `FORMULA_VERSION`.
- Explorer com os mesmos operadores das regras de filtro, busca literal (`contains`) e tempo-limite de 10 s (ADR-020).

## Erros conhecidos / limitações

- Gráfico da visão geral agrupa por dia em UTC.
- Objetos órfãos no S3 se o commit do upload falhar após o envio (limpeza prevista na Fase 5).
- `peak_memory_mb` só é medido em Linux.
- Worker Celery em Windows exige `--pool solo` (o Compose usa Linux).
- XLSX ~40× mais lento que CSV (duas passadas do openpyxl em Python; ≈ 2.470 registros/s); tabela de textos compartilhados inteira em memória; não medido perto de 25 MB.
- Deduplicação mantém chave e número do registro da versão inteira em memória; não medida acima de 100 mil registros.
- A prévia de transformações vê só os primeiros 200 registros (a análise de duplicidades da versão inteira é separada).
- Excluir um dataset ainda não existe na interface; conjuntos de regras e versões seguem o dataset por `ON DELETE CASCADE`.

## Próxima tarefa

1. **Mesclar o PR #1 (Fase 2)** na `main` quando o usuário decidir; depois, abrir o PR da Fase 3 (`fase-3-qualidade`) para a CI validar e registrar a execução aqui.
2. **Fase 4 — Business Intelligence**, conforme o prompt mestre: dashboard geral com KPIs reais (soma, média, máximo, mínimo, contagem distinta, por categoria, evolução temporal, comparação entre períodos) sem presumir que coluna numérica é receita; gráficos de linha, barras, barras horizontais, área, pizza/rosca, tabelas analíticas e cards KPI; filtros por período, categoria, status, responsável, faixa de valores e colunas personalizadas, respeitando o tipo de cada coluna; Dashboard Builder com `Dashboard` e `DashboardWidget` persistidos (dataset e versão, widgets, tipo de gráfico, dimensão, métrica e agregação, filtros, reorganização e reabertura). Tudo renderizado a partir da API (DuckDB com construtor de consultas por colunas e operações permitidas, reaproveitando `build_where` do explorer).
