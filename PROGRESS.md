# PROGRESS — DataFlow Analytics

Documento de retomada. Atualizado em **30/10/2026**.

## Fases

| Fase | Status |
| --- | --- |
| 1 — Fundação e primeiro dataset | ✅ Concluída e validada na CI com a infraestrutura real, nos Compose de desenvolvimento e de produção |
| 2 — Motor ETL (XLSX, transformações, deduplicação, reprocessamento) | ⏳ Próxima |
| 3 — Qualidade e Data Explorer completo | Pendente |
| 4 — Business Intelligence (dashboards) | Pendente |
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

## Testes executados localmente (29/10/2026, Windows 10, sem Docker)

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

Não bloqueiam a Fase 2, mas ainda não foram exercitados em nenhum ambiente, porque dependem de uma implantação real:

- Certificado público (Let's Encrypt) com domínio real; a CI usa a CA interna do Caddy.
- SMTP real com TLS e autenticação; a CI usa o Mailpit, sem TLS.
- Atualização de uma instalação existente e restauração de backup.

O Docker Desktop foi instalado na máquina de desenvolvimento, mas não inicia (`Docker Desktop is unable to start`, em 30/10/2026). Enquanto isso, o ambiente em contêineres só roda na CI.

## Arquivos relevantes

| Área | Arquivos |
| --- | --- |
| Configuração | `backend/app/core/config.py`, `.env.example` |
| Modelos / migrations | `backend/app/models/*`, `backend/migrations/versions/20261029_0001_initial_schema.py` |
| Autenticação | `backend/app/services/auth_service.py`, `backend/app/api/routes/auth.py`, `backend/app/api/deps.py`, `backend/app/api/middleware.py` |
| Upload / preview / importação | `backend/app/services/{upload,preview,import}_service.py` |
| Pipeline | `backend/app/processing/{inspection,inference,reader,convert,pipeline,types}.py` |
| Worker | `backend/app/services/job_runner.py`, `backend/app/tasks/*` |
| Consultas | `backend/app/analytics/{query,cache}.py` |
| Frontend | `apps/web/src/app/router.tsx`, `apps/web/src/pages/**`, `apps/web/src/features/**`, `apps/web/src/services/api-client.ts` |
| Infra | `docker-compose.yml`, `docker-compose.prod.yml`, `docker/**`, `.github/workflows/ci.yml` |
| Dados | `scripts/generate_samples.py`, `samples/` |

## Decisões que não podem se perder

- MinIO via `cgr.dev/chainguard/minio` (imagem oficial indisponível; ADR-006).
- Tokenização com `csv` + conversão com Polars (Polars preenche campos ausentes em silêncio; ADR-004).
- Decimais como `Decimal(38, escala)`, trafegando como texto na API; escala excedida rejeita (ADR-005).
- Estado de job no PostgreSQL; Celery só transporte; reivindicação condicional (ADR-001).
- Upload por corpo binário em streaming, não multipart (ADR-008).
- TypeScript 5.9, React Router 7, TanStack Table 8, DuckDB 1.5 por compatibilidade (ADR-011).

## Erros conhecidos / limitações

- Gráfico da visão geral agrupa por dia em UTC.
- Objetos órfãos no S3 se o commit do upload falhar após o envio (limpeza prevista na Fase 5).
- `peak_memory_mb` só é medido em Linux.
- Worker Celery em Windows exige `--pool solo` (o Compose usa Linux).

## Próxima tarefa

**Fase 2 — Motor ETL.** Escopo definido no prompt mestre, registrado aqui para retomar sem depender da conversa:

- **XLSX:** limite de 25 MB configurável; selecionar a aba; visualizar colunas e identificar o intervalo de dados; processar abas diferentes em importações independentes. Não executar macros nem fórmulas; fórmula sem valor calculado é dado ausente ou inválido, de forma explícita. Validar conteúdo real, recusar XLSX malformado, limitar a descompressão interna (zip bomb) e tratar planilhas criptografadas. Reconhecer as limitações de memória da biblioteca de leitura.
- **Mapeamento:** além de nome, tipo e formato (já prontos), coluna obrigatória e regra para valores nulos.
- **Transformações configuráveis** (`TransformationSet` e `TransformationRule`), só com operações conhecidas e validadas no backend, sem `eval` nem código enviado pelo usuário: remover espaços excedentes, normalizar texto, padronizar maiúsculas e minúsculas, converter tipos, tratar nulos, remover linhas totalmente vazias, padronizar datas, corrigir formatos numéricos, filtrar registros, identificar e remover duplicidades, renomear colunas e criar colunas derivadas com operações permitidas.
- **Deduplicação:** comparar por todas as colunas ou por colunas selecionadas; manter o primeiro ou o último registro; prévia dos duplicados e contagem de afetados. Registrar claramente se duplicados entram ou não nos válidos, com categorias da reconciliação mutuamente consistentes (hoje `duplicates` é `null`, com `duplicates_policy: "nao_aplicada"`).
- **Reprocessamento e versionamento:** novas versões a partir de versões existentes (ex.: v2 trata nulos, v3 remove duplicidades), cada uma identificando origem, transformações, data e responsável. Versões publicadas seguem imutáveis e os dados originais nunca são sobrescritos.
- **Histórico:** cada execução registra quem iniciou, início e fim, arquivo de origem, configuração, versão das regras, totais recebido, preservado, rejeitado e duplicado, e erros encontrados.
- **Interface:** a tela Transformações sai de "Em desenvolvimento"; a importação passa a aceitar XLSX, hoje recusado com aviso.
- **Critério de conclusão:** implementado e integrado de ponta a ponta, utilizável na interface, com dados persistidos, testes executados, compilando, erros conhecidos documentados e README atualizado.
