# DataFlow Analytics

Plataforma de engenharia de dados e Business Intelligence: transforma planilhas CSV brutas em datasets tratados, versionados e consultáveis — com rastreabilidade de cada registro recebido.

> **Status:** Fase 1 de 6 concluída (fundação e primeiro dataset). Veja [PROGRESS.md](PROGRESS.md) para o estado detalhado, testes executados e pendências.

![Visão geral](docs/screenshots/02-visao-geral.png)

## Problema resolvido

Equipes de vendas, atendimento e operações vivem de planilhas exportadas de sistemas diferentes: delimitadores diferentes, `1.234,56` misturado com `1234.56`, datas em `dd/mm` e `mm/dd`, linhas incompletas. Ferramentas de BI costumam descartar ou converter esses dados em silêncio. O DataFlow trata a importação como um **pipeline auditável**: cada registro é contabilizado como válido ou rejeitado, com motivo, coluna, linha e valor original — e cada processamento gera uma **versão imutável** do dataset.

## Funcionalidades (Fase 1)

- **Contas e workspaces**: cadastro, login, logout, recuperação de senha por e-mail; Argon2id; sessões HttpOnly; CSRF; rate limiting; RBAC (Administrador, Analista, Visualizador); isolamento entre workspaces validado no servidor; auditoria.
- **Importação de CSV**: drag-and-drop, progresso real de envio, streaming com limite aplicado durante o recebimento, validação de conteúdo real (não só extensão), armazenamento privado no MinIO com nome aleatório.
- **Pré-visualização**: 20 primeiras linhas, contagem exata ou estimada (informando qual), tipos inferidos, nulos, distintos, avisos de encoding, datas ambíguas e registros malformados.
- **Mapeamento**: renomear colunas, escolher tipo, formato de data e casas decimais; bloqueio de nomes duplicados; confirmação explícita de datas ambíguas; mapeamento salvo e reutilizado.
- **Processamento assíncrono** (Celery + Redis): estados duráveis no PostgreSQL, progresso medido por bytes lidos, cancelamento cooperativo, retentativas, idempotência, recuperação de jobs interrompidos.
- **Versionamento**: Parquet por versão (válidos + rejeitados), publicação atômica, reconciliação `recebidos = válidos + rejeitados`, métricas de execução.
- **Data Explorer**: paginação e ordenação no servidor (DuckDB sobre Parquet), seleção de versão, formatação pt-BR por tipo — decimais sem perda de precisão e sem formato monetário automático.
- **Interface**: tema escuro padrão e tema claro, sidebar recolhível, responsiva, navegável por teclado, estados vazios, skeletons, toasts, erros claros. Módulos das próximas fases aparecem como **"Em desenvolvimento"**.

## Capturas de tela

Geradas por `e2e/tests/screenshots.spec.ts` a partir de um fluxo real com os dados fictícios de `samples/`.

| | |
| --- | --- |
| ![Login](docs/screenshots/01-login.png) | ![Importar](docs/screenshots/03-importar.png) |
| ![Pré-visualização](docs/screenshots/04-preview.png) | ![Processamento concluído](docs/screenshots/05-job-concluido.png) |
| ![Rejeições rastreáveis](docs/screenshots/06-rejeicoes.png) | ![Data Explorer](docs/screenshots/07-explorer.png) |

## Stack

| Camada | Tecnologias |
| --- | --- |
| Frontend | React 19, TypeScript 5.9, Vite 8, Tailwind CSS 4, shadcn/ui (Radix), React Router 7, TanStack Query 5, TanStack Table 8, React Hook Form, Zod 4, Recharts 3, Lucide |
| Backend | Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2.1, Alembic, Celery 5.6, Polars 2.1, PyArrow, DuckDB 1.5, boto3, Argon2 |
| Dados | PostgreSQL 17 (metadados), MinIO/S3 (arquivos e Parquet), Redis 8 (fila e rate limit), DuckDB (consultas) |
| Infra | Docker Compose, Caddy (proxy, HTTPS, CSP), Mailpit (e-mail em dev), GitHub Actions |
| Qualidade | Pytest, Vitest + Testing Library, Playwright, Ruff, mypy (strict), ESLint, Prettier |
| Ferramentas | `uv` (Python), `pnpm` (Node) |

Versões exatas e justificativas em [docs/decisions.md](docs/decisions.md#adr-011--versões-das-dependências).

## Arquitetura

```mermaid
flowchart LR
    B[Navegador] --> C[Caddy] --> A[FastAPI]
    A --> P[(PostgreSQL)]
    A --> R[(Redis)]
    A --> M[(MinIO)]
    A --> D[DuckDB]
    R --> W[Celery worker] --> P
    W --> M
    W --> PL[csv + Polars + PyArrow]
```

API e worker compartilham o mesmo pacote de domínio (`backend/app`). Detalhes em [docs/architecture.md](docs/architecture.md); pipeline e regras em [docs/data-pipeline.md](docs/data-pipeline.md); segurança em [docs/security.md](docs/security.md).

## Como executar

### Com Docker (recomendado)

Requisitos: Docker Engine/Desktop com Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

| Serviço | Endereço |
| --- | --- |
| Aplicação | http://localhost:8080 |
| Documentação da API (OpenAPI) | http://localhost:8080/api/docs |
| E-mails de desenvolvimento (Mailpit) | http://localhost:8025 |
| Console do MinIO | http://localhost:9001 |

### Desenvolvimento local (hot reload)

Suba só a infraestrutura e rode API, worker e frontend na máquina:

```bash
docker compose up -d postgres redis minio-perms minio mailpit
cp .env.example .env

cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.scripts.init_storage
uv run uvicorn app.main:app --reload --port 8000
# em outro terminal:
uv run celery -A app.tasks.celery_app worker -Q default,imports --loglevel INFO --pool solo

cd apps/web
pnpm install
pnpm dev        # http://localhost:5173 (proxy de /api para :8000)
```

## Como importar um dataset

1. Crie uma conta em **Cadastro** (você vira administrador do novo workspace).
2. Em **Importar dados**, arraste `samples/vendas_1000.csv` (ou clique em *Selecionar arquivo*).
3. Clique em **Configurar e processar**: confira encoding, delimitador, separadores e o mapeamento de colunas.
4. **Iniciar processamento** e acompanhe as etapas em tempo real.
5. Na conclusão, veja a reconciliação e as rejeições; clique em **Ver registros** para o Data Explorer.

Para ver rejeições rastreáveis, importe `samples/qualidade_1000.csv` e defina `data_venda` como Data, `quantidade` como Inteiro e `valor` como Decimal.

## Testes

```bash
cd backend && uv run pytest                   # 58 testes (SQLite + S3/Redis simulados)
TEST_DATABASE_URL=postgresql+psycopg://dataflow:dataflow@localhost:5432/dataflow_test uv run pytest
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app

cd apps/web && pnpm test && pnpm lint && pnpm typecheck && pnpm build

python scripts/generate_samples.py --rows 100000 --only vendas  # habilita o E2E de 100 mil linhas
cd e2e && pnpm install && pnpm exec playwright install chromium
E2E_BASE_URL=http://localhost:8080 pnpm test  # com o Docker Compose em execução
```

A CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) roda lint, formatação, tipos, testes com PostgreSQL real, migrations em banco descartável (upgrade → check → downgrade → upgrade), build, validação dos arquivos Compose, subida do ambiente completo e E2E.

## Dados de demonstração

```bash
python scripts/generate_samples.py                 # 1.000, 10.000 e 100.000 linhas em samples/generated/
python scripts/generate_samples.py --rows 1000000 --only vendas --seed 7
```

Vendas, atendimentos e um dataset com problemas propositais de qualidade. Todos fictícios e reproduzíveis — ver [samples/README.md](samples/README.md).

## API

Base `/api/v1`, documentação interativa em `/api/docs`. Erros sempre no formato `{"error": {"code", "message", "details"}, "request_id"}`.

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/auth/csrf` | Token CSRF (anônimo ou da sessão) |
| POST | `/auth/register` · `/auth/login` · `/auth/logout` | Cadastro, login, logout |
| GET | `/auth/me` | Usuário, workspace ativo, permissões |
| POST | `/auth/password/forgot` · `/auth/password/reset` | Recuperação de senha |
| GET | `/workspaces` · `/workspaces/current` · `/workspaces/current/members` | Workspaces e membros |
| POST | `/workspaces/switch` | Troca de workspace (valida pertencimento) |
| POST | `/datasets/upload` | Upload em streaming (`application/octet-stream`, cabeçalho `X-File-Name`) |
| GET | `/datasets` | Lista paginada com busca e filtro de status |
| GET | `/datasets/{id}` · `/columns` · `/versions` | Detalhe, mapeamento, versões |
| GET / POST | `/datasets/{id}/preview` | Pré-visualização (opções salvas / opções de teste) |
| PUT | `/datasets/{id}/parse-options` | Salva configuração de leitura |
| POST | `/datasets/{id}/imports` | Inicia processamento (`Idempotency-Key` opcional) |
| GET | `/datasets/{id}/rows` | Registros paginados (`version_id`, `page`, `page_size ≤ 200`, `sort`, `direction`, `columns`) |
| GET | `/datasets/{id}/versions/{vid}/rejected` | Registros rejeitados com motivo |
| GET | `/jobs` · `/jobs/{id}` | Histórico e detalhe de processamentos |
| POST | `/jobs/{id}/cancel` | Cancelamento cooperativo |
| GET | `/overview` | Indicadores reais do workspace |
| GET | `/health/live` · `/health/ready` | Saúde do processo e das dependências |

## Deploy

`docker-compose.prod.yml` sobe tudo em um host com HTTPS automático (Caddy), apenas as portas 80/443 expostas e segredos obrigatórios por variável de ambiente. Passo a passo, backups e escala em [docs/deploy.md](docs/deploy.md).

## Benchmark

Fluxo completo com Caddy, PostgreSQL, Redis, MinIO e Celery reais, medido na CI (GitHub Actions, worker limitado a 2 CPUs e 2 GB): **job de 100 mil linhas (8 MB) em 0,74 s**, cerca de 135 mil registros/s, pico de 313 MB de RSS no worker e consulta ordenada no fim do dataset em ~60 ms. É uma única execução em runner compartilhado; método, ressalvas e reprodução em [docs/benchmark.md](docs/benchmark.md).

## Limitações conhecidas

- Somente CSV na Fase 1 (XLSX chega na Fase 2, com seleção de abas e proteções contra arquivos compactados maliciosos).
- Sem transformações configuráveis nem deduplicação ainda (Fase 2); duplicados aparecem como "não avaliado".
- Data Explorer sem filtros, busca e seleção de colunas na interface (Fase 3; a API já aceita seleção de colunas).
- Gestão de membros, exportações, auditoria na interface e retenção de arquivos: Fase 5.
- Gráfico da visão geral agrupa por dia em UTC (fuso por workspace chega com as configurações).
- O MinIO Community foi arquivado; o projeto usa a imagem mantida pela Chainguard (ver ADR-006).
- A CI valida o ambiente completo em contêineres, mas o envio real de e-mail e o Compose de produção em execução ainda não foram exercitados; ver PROGRESS.md.

## Roadmap

| Fase | Escopo |
| --- | --- |
| 1 ✅ | Fundação, autenticação, workspaces, upload CSV, preview, worker, versão Parquet, explorer paginado |
| 2 | XLSX e abas, transformações configuráveis, deduplicação, reprocessamento a partir de versões |
| 3 | Qualidade dos dados (pontuação documentada), Data Explorer com filtros, busca e seleção de colunas |
| 4 | Dashboards, KPIs, gráficos, filtros dinâmicos, comparação temporal, construtor de dashboards |
| 5 | Relatórios, exportações CSV/XLSX em segundo plano, gestão de usuários, auditoria, retenção |
| 6 | Testes ampliados, benchmarks com infraestrutura, revisão de segurança e performance, deploy |
