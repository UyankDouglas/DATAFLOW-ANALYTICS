# PROGRESS — DataFlow Analytics

Documento de retomada. Atualizado em **03/11/2026**.

## Fases

| Fase | Status |
| --- | --- |
| 1 — Fundação e primeiro dataset | ✅ Concluída e validada na CI com a infraestrutura real, nos Compose de desenvolvimento e de produção |
| 2 — Motor ETL (XLSX, transformações, deduplicação, reprocessamento) | ✅ Concluída, validada na CI com a infraestrutura real e mesclada na `main` ([PR #1](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/pull/1)) |
| 3 — Qualidade e Data Explorer completo | ✅ Concluída e validada na CI com a infraestrutura real ([PR #2](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/pull/2)) |
| 4 — Business Intelligence (dashboards) | ✅ Concluída e validada na CI com a infraestrutura real ([PR #3](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/pull/3)) |
| 5 — Relatórios, exportações e administração | ✅ Implementada e validada localmente (sem Docker); [PR #4](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/pull/4) aberto, aguardando a CI |
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

## Fase 4 — concluído

- [x] **Consultas analíticas** (`analytics/aggregate.py`, `services/analytics_service.py`, `POST /datasets/{id}/analytics`): medidas de vocabulário fechado (contagem, contagem distinta, soma, média, mínimo, máximo) validadas pelo tipo da coluna; dimensão por categoria ou data (dia, semana, mês, trimestre, ano); grupos além do limite em "Outros", calculado sobre os registros restantes; séries temporais sem corte (acima de 1.000 pontos, pede granularidade maior); comparação com o período anterior de mesma duração ou com o ano anterior numa só leitura (`FILTER`); filtros tipados do explorer e grupos extras com o próprio E/OU; tempo-limite de 10 s (ADR-021).
- [x] **Resultado tipado, sem presumir dinheiro**: cada medida informa tipo e escala (média com duas casas além da escala da coluna); decimais como texto; nada formatado como moeda.
- [x] **Dashboards persistidos** (`models/dashboard.py`, tabelas `dashboards` e `dashboard_widgets`, migration 0004 aditiva): dataset, versão fixa ou sempre a atual, filtros gerais e até 24 widgets com tipo, tamanho, posição e consulta; CRUD em `/dashboards` e cálculo de cada widget em `POST /dashboards/{id}/query` com os filtros da tela (ADR-022).
- [x] **Validação ao salvar** contra a versão resultante, com regras por tipo de gráfico (KPI sem dimensão; pizza e rosca só com contagem ou soma sobre categoria; linha e área sem comparação); o erro aponta o widget (`invalid_widget`). Widget que deixou de ser compatível com a versão atual responde `widget_incompatible` sem derrubar os outros.
- [x] **Reorganização** pela lista enviada no `PATCH`, mantendo o id dos widgets; duplicar e remover no construtor.
- [x] **Permissão nova** `dashboards:manage` (Analista e Administrador); Visualizador abre, filtra e usa o Dashboard geral. Auditoria `dashboard.created`, `dashboard.updated` e `dashboard.deleted`. Isolamento por workspace em todas as rotas, inclusive ao apontar dataset ou versão de outro workspace.
- [x] **Interface**:
  - **Dashboard geral** (`/dashboards/geral`): dataset, versão, medida, categoria, data e granularidade escolhidas pelo usuário; KPIs, evolução temporal, barras, rosca, tabela analítica e comparação entre períodos, com período sugerido a partir dos dados.
  - **Dashboards**: lista e exclusão com confirmação.
  - **Dashboard salvo**: filtros interativos (período, valores de uma coluna, faixa e filtros avançados) e widgets calculados um a um.
  - **Construtor** (`/dashboards/construtor`): editor de widget com prévia ao vivo; setas para reorganizar; duplicar e remover.
  - Gráficos Recharts com tabela equivalente para leitores de tela; sem rolagem horizontal em 375 px. Dashboards e Construtor saíram de "Em desenvolvimento".
- [x] **Benchmark**: `benchmark_pipeline` mede KPIs, agrupamento com "Outros", série mensal e comparação entre períodos.
- [x] **Documentação**: `docs/dashboards.md` (novo), ADR-021 e ADR-022, `security.md`, `architecture.md`, `benchmark.md`, README; capturas 13, 14 e 15, e as demais regeneradas.

## Fase 5 — concluído

- [x] **Exportações em segundo plano** (`models/export.py` `ExportJob`, `services/export_service.py`, `services/export_runner.py`, tarefa `exports.run`, migration 0005 aditiva):
  - registros tratados (filtros, busca, colunas e ordenação do explorer, mais os grupos de filtros da tela) ou um relatório agregado;
  - CSV para Excel em português, CSV padrão ou XLSX;
  - volume conferido antes de enfileirar (500 mil em CSV, 100 mil em XLSX, 3 em andamento por workspace);
  - arquivo no MinIO com validade e download só pela API, com auditoria;
  - expiração e recuperação pelo beat (ADR-023).
- [x] **Proteção contra formula injection** nas exportações (`processing/export_writers.py`): apóstrofo em texto iniciado por `=`, `+`, `-`, `@`, tab, CR ou variantes de largura total; no XLSX, texto sempre como texto e caracteres de controle removidos; números, datas e booleanos tipados.
- [x] **Relatórios**: agrupamento, até 6 medidas, filtros e comparação entre períodos, reaproveitando `analytics/aggregate.py`; exportação do relatório (até 10 mil grupos) e dos registros filtrados.
- [x] **Membros e convites** (`services/members_service.py`, `WorkspaceInvitation`):
  - convite por e-mail com hash do token e validade de 7 dias, enviado pelo worker (`email.invitation`);
  - aceite só pela conta do e-mail convidado, com troca de perfil e remoção;
  - proteção do último administrador e limite de 50 convites por hora (ADR-024).
- [x] **Permissões efetivas**: a configuração "visualizadores podem exportar" concede `data:export` ao Visualizador, recalculado a cada requisição e exposto em `/auth/me`.
- [x] **Auditoria consultável** (`GET /audit`, só Administrador): filtros por ação exata ou categoria e por período, paginação; rótulos em português na tela.
- [x] **Configurações do workspace** (`workspaces.settings`): nome, validade das exportações, exportação por visualizadores e retenção dos originais, com auditoria do antes e depois.
- [x] **Retenção dos originais** (`services/retention_service.py`, beat a cada 6 h): apaga originais mais antigos que o prazo, nunca de datasets sem versão ou em processamento; pré-visualização e reprocessamento respondem 410 `original_purged`; aviso no detalhe do dataset (ADR-025).
- [x] **Exclusão controlada** (`services/deletion_service.py`):
  - impacto mostrado antes; exclusão do dataset confirmada pelo nome;
  - bloqueio com processamento ou exportação em andamento, versão fixada por dashboard ou única versão;
  - ordem explícita no banco e limpeza do MinIO e do cache depois; a versão anterior vira a atual quando necessário (ADR-025).
- [x] **Interface**:
  - telas Relatórios, Exportações (histórico com atualização automática), Usuários e permissões (convites, perfis, remoção), Auditoria, Configurações e a página do convite (`/convite`, com cadastro e retorno);
  - botão Exportar no Data Explorer e diálogos de exclusão no detalhe do dataset.
  - Nada mais aparece como "Em desenvolvimento".
- [x] **Benchmark**: `benchmark_pipeline` mede a exportação da versão inteira em CSV e XLSX.
- [x] **Documentação**: `docs/administration.md` (novo), ADR-023 a ADR-025, `security.md`, `architecture.md`, `deploy.md`, `benchmark.md`, README; capturas 16, 17 e 18, e as demais regeneradas.

## Testes executados na CI — Fase 4 (03/11/2026, commit `f403a9e`, [execução 41699024371](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41699024371), PR #3)

| Verificação | Resultado |
| --- | --- |
| Backend contra **PostgreSQL 17 real** | **169 passed**, cobertura de 89% |
| Alembic `upgrade` (inclui `0003 -> 0004`) → `check` → `downgrade` → `upgrade` no PostgreSQL | OK; `check`: "No new upgrade operations detected" |
| Ruff e mypy estrito | sem problemas (86 arquivos) |
| Frontend: formatação, lint, tipos, Vitest, build | OK, **84 passed** |
| E2E em desenvolvimento, com Celery, MinIO e Redis reais | **13 passed**, 1 ignorado (capturas de tela), sem retentativas — inclui `dashboards.spec.ts` (dashboard geral; criar, filtrar, reabrir e reorganizar) |
| E2E em produção, em HTTPS | **12 passed**, 2 ignorados (e-mail e capturas de tela), sem retentativas |
| CSV de 100 mil linhas pela interface | job de 534 ms em desenvolvimento e 875 ms em produção (187.266 e 114.286 registros/s); pico de RSS do worker 374 e 373 MB |

## Testes executados na CI — Fase 3 (03/11/2026, commit `06ca88b`, [execução 41683893654](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41683893654), PR #2)

| Verificação | Resultado |
| --- | --- |
| Backend contra **PostgreSQL 17 real** | **139 passed**, cobertura de 88% |
| Alembic `upgrade` (inclui `0002 -> 0003`) → `check` → `downgrade` → `upgrade` no PostgreSQL | OK; `check`: "No new upgrade operations detected" |
| Ruff e mypy estrito | sem problemas (79 arquivos) |
| Frontend: formatação, lint, tipos, Vitest, build | OK, **47 passed** |
| E2E em desenvolvimento, com Celery, MinIO e Redis reais | **11 passed**, 1 ignorado (capturas de tela) — inclui `quality.spec.ts` (relatório publicado pelo worker, inconsistências, explorer com busca, filtro e colunas) |
| E2E em produção, em HTTPS | **10 passed**, 2 ignorados (e-mail e capturas de tela) |
| CSV de 100 mil linhas pela interface | job de 929 ms em desenvolvimento e 702 ms em produção (107.643 e 142.450 registros/s); pico de RSS do worker 371 e 369 MB. O tempo vai até a publicação da versão; o relatório de qualidade é calculado logo depois, fora dele |

A primeira execução ([41682378950](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41682378950), commit `3cd6497`) falhou só no E2E de desenvolvimento: com os dois testes novos de qualidade, a suíte passou a criar 11 contas a partir do mesmo IP, acima do limite de 10 cadastros por hora, e o teste do explorer era barrado no cadastro. O limite ficou configurável (`REGISTER_LIMIT_PER_HOUR`, padrão 10, também no Compose de produção) e só os jobs de E2E da CI o elevam para 100 (commit `06ca88b`).

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

## Testes executados localmente — Fase 5 (03/11/2026, Windows 10, sem Docker)

| Comando | Resultado |
| --- | --- |
| `cd backend && uv run pytest --cov=app` | **205 passed** (36 novos: `test_export_writers.py` ×13, `test_exports_api.py` ×11, `test_members_api.py` ×5, `test_admin_api.py` ×7), cobertura de 89% |
| `uv run ruff format --check . && uv run ruff check .` / `uv run mypy app` | sem problemas (99 arquivos no mypy) |
| Alembic `upgrade head` → `downgrade 0004` → `upgrade head` + `check` no SQLite; `upgrade 0004:0005 --sql` para PostgreSQL | OK (`DEFAULT '{}'` na coluna `settings`; o `check` não aponta nada da 0005) |
| `cd apps/web && pnpm test` | **99 passed** (28 arquivos; 15 novos); lint, typecheck, format e build OK |
| `cd e2e && E2E_BASE_URL=http://localhost:5173 pnpm test` | **14 passed**, 4 ignorados. Os ignorados: convite e recuperação de senha precisam do Mailpit, o limite do proxy precisa do Caddy, as capturas são sob demanda. Novos: `exports.spec.ts` ×2 (explorer → CSV filtrado conferido linha a linha, outro workspace recebe 404; relatório → XLSX) e `admin.spec.ts` (configurações, auditoria e exclusão controlada) |
| `CAPTURE_SCREENSHOTS=1 … pnpm test screenshots` | 18 capturas em `docs/screenshots/` |
| Verificação manual no navegador | relatório agrupado, exportação XLSX pronta e baixada (assinatura `PK`, `no-store`, contagem de downloads), convite enviado → link → "Criar conta" → volta ao convite → aceito como Analista, auditoria do fluxo inteiro, configurações, diálogo de exclusão com o impacto |
| `uv run python -m app.scripts.benchmark_pipeline …100000.csv` | exportação de 100 mil registros: CSV 1,6–2,0 s; XLSX 23,5–28,6 s |

**Ainda não validado (depende da CI):**
- suíte contra PostgreSQL com a migration 0005 e `alembic check` no PostgreSQL;
- exportações com MinIO e Celery reais;
- o E2E do convite com o e-mail real no Mailpit, em desenvolvimento;
- os E2E da Fase 5 em produção.

**Corrigido durante a verificação:**
- o aviso da tela Exportações quebrava em pedaços;
- a coluna de detalhes da auditoria invadia a do IP (ids agora com 8 caracteres);
- o teste E2E lia a contagem do explorer antes da resposta filtrada.

## Testes executados localmente — Fase 4 (03/11/2026, Windows 10, sem Docker)

| Comando | Resultado |
| --- | --- |
| `cd backend && uv run pytest --cov=app` | **169 passed** (30 novos: `test_analytics.py` ×22 e `test_dashboards_api.py` ×8), cobertura de 89% (`aggregate.py` 98%, `dashboards_service.py` 94%) |
| `uv run ruff format --check . && uv run ruff check .` / `uv run mypy app` | sem problemas (86 arquivos no mypy) |
| Alembic `upgrade head` → `downgrade 0003` → `upgrade head` + `check` no SQLite; `upgrade 0003:0004 --sql` para PostgreSQL | OK (o `check` só aponta as FKs por `ALTER` que o SQLite não cria; nenhuma da 0004) |
| `cd apps/web && pnpm test` | **84 passed** (22 arquivos; 37 novos); lint, typecheck, format e build OK |
| `cd e2e && E2E_BASE_URL=http://localhost:5173 pnpm test` | **11 passed**, 3 ignorados (limite do proxy sem Caddy, e-mail sem Mailpit, capturas); inclui `dashboards.spec.ts` ×2 (dashboard geral; criar, filtrar, reabrir e reorganizar). Na primeira rodada da suíte inteira, o primeiro teste falhou ainda no cadastro, antes de qualquer tela da Fase 4; passou nas três rodadas seguintes |
| `CAPTURE_SCREENSHOTS=1 … pnpm test screenshots` | 15 capturas em `docs/screenshots/` |
| Verificação manual no navegador | dashboard geral, filtros por valores e por faixa, construtor com prévia, salvar, reabrir e reorganizar; sem rolagem horizontal em 375 px nas quatro telas. Números conferidos com o CSV lido pelo Polars, fora do pipeline: somas por equipe, filtro "pago" com valor ≥ 1000 e comparação de dezembro |
| `uv run python -m app.scripts.benchmark_pipeline …100000.csv` | KPIs em 0,04–0,05 s; por categoria com "Outros" em 0,05–0,08 s; série mensal em 0,05 s; comparação entre períodos em 0,05–0,09 s |

Validação na CI: ver "Testes executados na CI — Fase 4" ([execução 41699024371](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41699024371)).

**Corrigido durante a verificação:**
- o construtor reenviava a posição dos widgets salvos ao editar, e a API recusava;
- a tabela para leitores de tela vazava da página no celular;
- escolher uma coluna depois de "Registros" mantinha a contagem em vez da soma.

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

Validação na CI: ver "Testes executados na CI — Fase 3" ([execução 41683893654](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions/runs/41683893654)).

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
| Modelos / migrations | `backend/app/models/*`, `backend/migrations/versions/20261029_0001_initial_schema.py`, `20261103_0002_transformacoes_e_xlsx.py`, `20261103_0003_relatorios_de_qualidade.py`, `20261103_0004_dashboards_e_widgets.py` |
| Autenticação | `backend/app/services/auth_service.py`, `backend/app/api/routes/auth.py`, `backend/app/api/deps.py`, `backend/app/api/middleware.py` |
| Upload / preview / importação | `backend/app/services/{upload,preview,import}_service.py` |
| Transformações | `backend/app/services/transformation_service.py`, `backend/app/api/routes/transformations.py`, `backend/app/schemas/transformation.py` |
| Pipeline | `backend/app/processing/{inspection,inference,reader,xlsx,convert,transforms,pipeline,types}.py` |
| Worker | `backend/app/services/job_runner.py`, `backend/app/tasks/*` |
| Consultas e qualidade | `backend/app/analytics/{query,quality,cache}.py`, `backend/app/services/quality_service.py`, `backend/app/api/routes/quality.py` |
| Exportações e administração | `backend/app/services/{export,members,retention,deletion}_service.py`, `backend/app/services/export_runner.py`, `backend/app/processing/export_writers.py`, `backend/app/api/routes/{exports,audit,workspaces}.py`, `apps/web/src/features/admin/`, `apps/web/src/pages/{reports,exports,audit,settings}/` |
| BI e dashboards | `backend/app/analytics/aggregate.py`, `backend/app/services/{analytics,dashboards}_service.py`, `backend/app/api/routes/dashboards.py`, `backend/app/schemas/{analytics,dashboard}.py`, `apps/web/src/features/dashboards/`, `apps/web/src/pages/dashboards/` |
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
- Consultas analíticas de vocabulário fechado, recalculadas a cada abertura, sem resultados guardados; "Outros" sobre os registros restantes; séries sem corte (ADR-021).
- Exportações: `ExportJob` próprio, volume conferido antes de enfileirar, arquivo temporário no MinIO e download só pela API; formula injection neutralizada com apóstrofo e texto tipado no XLSX (ADR-023).
- Convites só com hash do token e aceite pelo e-mail convidado; permissões efetivas = perfil + concessões das configurações do workspace; nunca sem administrador (ADR-024).
- Exclusão com impacto antes, ordem explícita e limpeza do armazenamento depois do commit; retenção só de originais (ADR-025).
- Dashboards guardam definições; versão nula acompanha a atual; tudo é revalidado ao salvar; widgets mantêm o id ao reorganizar (ADR-022). As regras por tipo de gráfico ficam no backend (`check_chart_rules`) e são espelhadas no frontend (`features/dashboards/rules.ts`) só para guiar a edição.

## Erros conhecidos / limitações

- Gráfico da visão geral agrupa por dia em UTC.
- Objetos órfãos no S3 se o commit do upload falhar após o envio (limpeza prevista na Fase 5).
- `peak_memory_mb` só é medido em Linux.
- Worker Celery em Windows exige `--pool solo` (o Compose usa Linux).
- XLSX ~40× mais lento que CSV (duas passadas do openpyxl em Python; ≈ 2.470 registros/s); tabela de textos compartilhados inteira em memória; não medido perto de 25 MB.
- Deduplicação mantém chave e número do registro da versão inteira em memória; não medida acima de 100 mil registros.
- A prévia de transformações vê só os primeiros 200 registros (a análise de duplicidades da versão inteira é separada).
- Excluir um dataset ainda não existe na interface; conjuntos de regras e versões seguem o dataset por `ON DELETE CASCADE`.
- Dashboards: vale a última gravação quando duas pessoas editam ao mesmo tempo; reorganização por setas (sem arrastar e soltar); consultas medidas até 100 mil registros. Versões fixadas por dashboards não podem ser excluídas (FK sem `ON DELETE`; a tela explica).
- Exportação XLSX lenta (≈ 3,6 mil registros/s, openpyxl em Python), por isso limitada a 100 mil registros.
- Objetos órfãos no MinIO quando a remoção falha depois do commit (ou o commit falha depois do envio) ainda não têm limpeza periódica.
- O nome sugerido do arquivo exportado usa o horário UTC.

## Próxima tarefa

1. **Validar a Fase 5 na CI** ([PR #4](https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/pull/4)) e registrar a execução:
   - PostgreSQL com a migration 0005 e `alembic check`;
   - exportações com MinIO e Celery reais;
   - convite com o Mailpit;
   - E2E em produção.
2. **Fase 6 — Qualidade e produção**, conforme o prompt mestre:
   - testes ampliados (unidade, integração e E2E de ponta a ponta: login → upload → preview → configuração → processamento → qualidade → dashboard → exportação);
   - benchmarks com a infraestrutura real (1 milhão de linhas, XLSX perto de 25 MB, exportações nos limites);
   - revisão de segurança e de performance;
   - limpeza de objetos órfãos;
   - deploy documentado e verificado.
