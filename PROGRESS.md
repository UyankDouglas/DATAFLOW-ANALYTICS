# PROGRESS — DataFlow Analytics

Documento de retomada. Atualizado em **29/10/2026**.

## Fases

| Fase | Status |
| --- | --- |
| 1 — Fundação e primeiro dataset | ✅ Implementada e testada (validação em contêineres pendente — ver abaixo) |
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

## Testes executados (29/10/2026, Windows 10, sem Docker)

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

## Pendente na Fase 1 (bloqueado pelo ambiente)

O Docker Desktop foi instalado na máquina de desenvolvimento, mas não inicia (`Docker Desktop is unable to start`, em 30/10/2026). Quando estiver funcionando:

1. `docker compose up --build` e verificar todos os healthchecks (em especial `minio-perms` + imagem Chainguard do MinIO e o healthcheck do worker).
2. `cd backend && TEST_DATABASE_URL=postgresql+psycopg://dataflow:dataflow@localhost:5432/dataflow_test uv run pytest` (suíte contra PostgreSQL real; o banco `dataflow_test` precisa ser criado).
3. `uv run alembic upgrade head && uv run alembic check` contra o PostgreSQL do Compose.
4. `cd e2e && pnpm test` contra http://localhost:8080 (Caddy → API → Celery real).
5. Medir o fluxo ponta a ponta com 100 mil linhas pela interface e completar `docs/benchmark.md` (valida também o limite de upload do Caddy acima de 2 MB, que o E2E com 1.000 linhas não exercita).

A CI roda a cada push na `main` e cobre os itens 1–4 sem depender desta máquina: acompanhe o resultado em https://github.com/UyankDouglas/DATAFLOW-ANALYTICS/actions.

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

Validar o ambiente em contêineres (itens pendentes acima). Em seguida, **Fase 2**: suporte a XLSX (openpyxl em modo somente leitura, sem fórmulas/macros, limites de descompressão, seleção de abas), motor de transformações configuráveis (`TransformationSet`/`TransformationRule`), deduplicação com prévia e reprocessamento a partir de versões.
