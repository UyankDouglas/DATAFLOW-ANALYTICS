# DataFlow Analytics

Plataforma de engenharia de dados e Business Intelligence: transforma planilhas CSV e XLSX brutas em datasets tratados, versionados e consultáveis — com rastreabilidade de cada registro recebido.

> **Status:** Fases 1 a 4 de 6 implementadas. As Fases 1 a 3 (fundação, motor ETL, qualidade e Data Explorer) foram validadas na CI com a infraestrutura real (PostgreSQL, Redis, MinIO e Celery), nos Compose de desenvolvimento e de produção; a Fase 4 (Business Intelligence) foi validada localmente, sem Docker, e ainda não passou pela CI. Veja [PROGRESS.md](PROGRESS.md) para o estado detalhado, testes executados e pendências.

![Visão geral](docs/screenshots/02-visao-geral.png)

## Problema resolvido

Equipes de vendas, atendimento e operações vivem de planilhas exportadas de sistemas diferentes: delimitadores diferentes, `1.234,56` misturado com `1234.56`, datas em `dd/mm` e `mm/dd`, linhas incompletas. Ferramentas de BI costumam descartar ou converter esses dados em silêncio. O DataFlow trata a importação e o tratamento como um **pipeline auditável**: cada registro é contabilizado como válido, rejeitado, filtrado ou duplicado, com motivo, regra, coluna e valor original — e cada processamento gera uma **versão imutável** do dataset, com a origem e as regras que a produziram.

## Funcionalidades

### Fase 4 — Business Intelligence

- **Dashboard geral**: escolha o dataset, a versão, a **medida numérica**, a categoria e a coluna de data. Total de registros, soma, média, máximo, mínimo e contagem distinta; evolução temporal por dia, semana, mês, trimestre ou ano; participação e tabela analítica por categoria; **comparação entre períodos** (anterior de mesma duração ou mesmo período do ano anterior). Nenhuma coluna numérica é tratada como receita: as medidas aparecem depois que o usuário escolhe.
- **Filtros interativos** aplicados no servidor sobre os dados reais: período, valores de uma coluna (categoria, status, responsável), faixa de valores e filtros avançados em qualquer coluna, respeitando o tipo de cada uma.
- **Construtor de Dashboards**: dataset e versão (fixa ou sempre a atual), filtros gerais e até 24 widgets — card KPI, linha, área, barras, barras horizontais, pizza, rosca e tabela analítica —, cada um com medidas e agregações, dimensão, ordenação, filtros próprios e comparação de períodos, com **prévia calculada pela API** enquanto se edita. Reorganizar, duplicar, redimensionar e salvar para reabrir depois.
- **Dashboards persistidos** (`Dashboard` e `DashboardWidget`): guardam só a definição; os números são recalculados pelo DuckDB a cada abertura. Ver [docs/dashboards.md](docs/dashboards.md).

### Fase 3 — qualidade e Data Explorer

- **Qualidade dos Dados**: relatório por versão, calculado pelo worker ao publicar (ou sob demanda), com **nota de 0 a 100** de fórmula documentada — `100 × (0,4 validade + 0,4 completude + 0,2 unicidade)`, ver [docs/quality.md](docs/quality.md). Mostra total, válidos, rejeitados, duplicados, nulos, completude, colunas com inconsistências e regras violadas.
- **Visualizações**: completude por coluna, distribuição de nulos, erros por categoria, frequência de valores, duplicidades por chave e comparação entre versões.
- **Tabela de inconsistências**: registro, linha, coluna, valor original, tipo do problema, regra violada e tratamento aplicado, filtrável e paginada no servidor.
- **Data Explorer completo**: filtros tipados (os mesmos operadores das regras de filtro, combinados por E ou OU), busca nas colunas de texto, seleção e ordem de colunas, contagem filtrada, ordenação e paginação no servidor, com limites de complexidade e tempo-limite de 10 s por consulta.

### Fase 2 — motor ETL

- **XLSX**: até 25 MB; escolha da aba e da linha do cabeçalho (detectada automaticamente, pulando títulos acima da tabela); intervalo de dados visível; outras abas viram datasets independentes. Fórmulas e macros **nunca são executados**: fórmula sem valor salvo rejeita o registro com motivo. Planilhas criptografadas, XLS/XLSM, ZIP malformado e bombas de descompressão são recusados antes de abrir.
- **Mapeamento**: coluna obrigatória e valor para vazios, além de nome, tipo, formato e casas decimais.
- **Transformações configuráveis**: conjuntos de regras reutilizáveis, com revisão, montados na tela Transformações a partir de 12 operações conhecidas — remover espaços, normalizar texto, maiúsculas/minúsculas, converter tipos, padronizar datas, corrigir números (`R$ 1.234,56`), tratar nulos, remover linhas vazias, filtrar, renomear, criar colunas derivadas e remover duplicidades. Nada de fórmula livre ou código: tudo validado no backend contra o esquema da versão.
- **Prévia** sobre os primeiros 200 registros, com o que seria excluído e por quê, antes de gravar qualquer coisa.
- **Deduplicação** por todas as colunas ou pelas escolhidas, mantendo o primeiro ou o último; **análise de duplicidades na versão inteira** (DuckDB) sem alterar dados.
- **Reprocessamento com linhagem**: cada aplicação gera uma nova versão a partir de uma versão existente (v1 → v2 → v3), registrando versão de origem, conjunto, revisão e regras congeladas no job.
- **Reconciliação** `recebidos = válidos + rejeitados + filtrados + duplicados`, com categorias mutuamente exclusivas e política explícita para duplicados.

### Fase 1 — fundação

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
| ![Dashboard salvo](docs/screenshots/15-dashboard.png) | ![Dashboard geral](docs/screenshots/13-dashboard-geral.png) |
| ![Construtor de Dashboards](docs/screenshots/14-construtor.png) | ![Qualidade dos Dados](docs/screenshots/11-qualidade.png) |
| ![Data Explorer com filtros](docs/screenshots/12-explorer-filtros.png) | ![Transformações](docs/screenshots/09-transformacoes.png) |
| ![Pré-visualização de XLSX](docs/screenshots/10-preview-xlsx.png) | |
| ![Login](docs/screenshots/01-login.png) | ![Importar](docs/screenshots/03-importar.png) |
| ![Pré-visualização](docs/screenshots/04-preview.png) | ![Processamento concluído](docs/screenshots/05-job-concluido.png) |
| ![Exclusões rastreáveis](docs/screenshots/06-rejeicoes.png) | ![Data Explorer](docs/screenshots/07-explorer.png) |

## Stack

| Camada | Tecnologias |
| --- | --- |
| Frontend | React 19, TypeScript 5.9, Vite 8, Tailwind CSS 4, shadcn/ui (Radix), React Router 7, TanStack Query 5, TanStack Table 8, React Hook Form, Zod 4, Recharts 3, Lucide |
| Backend | Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2.1, Alembic, Celery 5.6, Polars 2.1, PyArrow, DuckDB 1.5, openpyxl 3.1 (somente leitura) + defusedxml, boto3, Argon2 |
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
    W --> PL[csv / openpyxl + Polars + PyArrow]
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

**Planilha:** importe `samples/vendas_atendimentos_1000.xlsx`. A aba "Vendas" tem um título acima da tabela; a pré-visualização detecta o cabeçalho na linha 3. Marque colunas como obrigatórias ou defina um valor para vazios no mapeamento. Use os botões de "Outras abas desta planilha" para importar "Atendimentos" ou "Totais" como datasets próprios — a aba "Totais" tem fórmulas sem valor salvo e mostra a rejeição explícita.

## Como transformar um dataset

1. No detalhe de um dataset processado, clique em **Transformar** (ou abra **Transformações** no menu).
2. Escolha a versão de origem, dê um nome ao conjunto e adicione regras; as colunas oferecidas acompanham as regras anteriores (renomeações, colunas derivadas, conversões).
3. **Gerar prévia** mostra os primeiros 200 registros transformados, as contagens e cada exclusão com motivo e regra.
4. No painel **Duplicidades na versão inteira**, escolha a chave e veja quantos registros seriam removidos, sem alterar nada.
5. **Salvar conjunto** e **Aplicar e gerar nova versão**: o job mostra a reconciliação, as regras aplicadas e os registros excluídos; o detalhe do dataset passa a listar a nova versão com a origem (`v1 + nome do conjunto`).

## Como montar um dashboard

1. Em **Dashboards**, abra o **Dashboard geral** para explorar um dataset: escolha a medida, a categoria e a data, e filtre por período, valores ou faixa.
2. Para guardar uma visão, clique em **Novo dashboard** (ou **Construtor** no menu; perfis Analista e Administrador): dê um nome, escolha o dataset e a versão — **Atual** acompanha as novas publicações, uma versão fixa congela os números.
3. Adicione widgets: tipo de gráfico, medidas e agregações, dimensão e filtros. A prévia é calculada com os dados reais da versão enquanto você edita.
4. Reorganize com as setas, duplique, remova e **Salvar dashboard**. Quem abrir o dashboard (inclusive o Visualizador) pode aplicar filtros na tela sem alterar o que foi salvo.

## Testes

```bash
cd backend && uv run pytest                   # 169 testes (SQLite + S3/Redis simulados)
TEST_DATABASE_URL=postgresql+psycopg://dataflow:dataflow@localhost:5432/dataflow_test uv run pytest
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app

cd apps/web && pnpm test && pnpm lint && pnpm typecheck && pnpm build

python scripts/generate_samples.py --rows 100000 --only vendas  # habilita o E2E de 100 mil linhas
cd e2e && pnpm install && pnpm exec playwright install chromium
E2E_BASE_URL=http://localhost:8080 pnpm test  # com o Docker Compose em execução
```

A CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) roda lint, formatação, tipos, testes com PostgreSQL real, migrations em banco descartável (upgrade → check → downgrade → upgrade), build e a subida dos Compose de desenvolvimento e de produção (em HTTPS com a CA interna do Caddy), com E2E nos dois.

## Dados de demonstração

```bash
python scripts/generate_samples.py                 # 1.000, 10.000 e 100.000 linhas em samples/generated/
python scripts/generate_samples.py --rows 1000000 --only vendas --seed 7
uv run --project backend python scripts/generate_samples.py --xlsx --rows 100000  # planilha com 3 abas
```

Vendas, atendimentos, um dataset com problemas propositais de qualidade e uma planilha XLSX com as mesmas vendas e atendimentos. Todos fictícios e reproduzíveis — ver [samples/README.md](samples/README.md).

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
| POST | `/datasets/upload` | Upload em streaming de CSV ou XLSX (`application/octet-stream`, cabeçalho `X-File-Name`) |
| POST | `/datasets/{id}/sheets` | Outra aba da mesma planilha como novo dataset |
| GET | `/datasets` | Lista paginada com busca e filtro de status |
| GET | `/datasets/{id}` · `/columns` · `/versions` | Detalhe, mapeamento, versões |
| GET / POST | `/datasets/{id}/preview` | Pré-visualização (opções salvas / opções de teste) |
| PUT | `/datasets/{id}/parse-options` | Salva configuração de leitura |
| POST | `/datasets/{id}/imports` | Inicia processamento (`Idempotency-Key` opcional) |
| GET | `/datasets/{id}/rows` | Registros paginados (`version_id`, `page`, `page_size ≤ 200`, `sort`, `direction`, `columns`) |
| GET | `/datasets/{id}/versions/{vid}/rejected` | Registros excluídos (rejeitados, filtrados, duplicados) com motivo e valor original |
| GET / POST | `/datasets/{id}/transformation-sets` | Lista e cria conjuntos de regras |
| GET / PUT / DELETE | `/datasets/{id}/transformation-sets/{sid}` | Detalhe, nova revisão, exclusão |
| POST | `/datasets/{id}/transformations/preview` | Aplica regras a uma amostra, sem gravar |
| POST | `/datasets/{id}/versions/{vid}/duplicates` | Análise de duplicidades na versão inteira |
| POST | `/datasets/{id}/transform-jobs` | Aplica um conjunto a uma versão (`Idempotency-Key` opcional) |
| POST | `/datasets/{id}/rows/query` | Data Explorer: filtros tipados, busca, colunas, ordenação e contagem filtrada |
| GET | `/datasets/{id}/quality` | Nota e componentes de cada versão (comparação) |
| GET / POST | `/datasets/{id}/versions/{vid}/quality` | Relatório de qualidade da versão / cálculo sob demanda |
| GET | `/datasets/{id}/versions/{vid}/quality/inconsistencies` | Inconsistências com regra e tratamento (`category`, `reason`, `column`, paginação) |
| GET | `/datasets/{id}/versions/{vid}/quality/values` | Valores mais frequentes de uma coluna |
| POST | `/datasets/{id}/analytics` | KPIs, agrupamentos, séries e comparação entre períodos sobre uma versão |
| GET / POST | `/dashboards` | Lista e cria dashboards |
| GET / PATCH / DELETE | `/dashboards/{id}` | Detalhe, alteração (nome, versão, filtros, widgets na nova ordem) e exclusão |
| POST | `/dashboards/{id}/query` | Calcula um widget com os filtros escolhidos na tela |
| GET | `/jobs` · `/jobs/{id}` | Histórico e detalhe de processamentos (`kind=import\|transform`) |
| POST | `/jobs/{id}/cancel` | Cancelamento cooperativo |
| GET | `/overview` | Indicadores reais do workspace |
| GET | `/health/live` · `/health/ready` | Saúde do processo e das dependências |

## Deploy

`docker-compose.prod.yml` sobe tudo em um host com HTTPS automático (Caddy), apenas as portas 80/443 expostas e segredos obrigatórios por variável de ambiente. Passo a passo, backups e escala em [docs/deploy.md](docs/deploy.md).

## Benchmark

Fluxo completo com Caddy, PostgreSQL, Redis, MinIO e Celery reais, medido na CI (GitHub Actions, worker limitado a 2 CPUs e 2 GB): **job de 100 mil linhas (8 MB) entre 0,74 s e 1,05 s** em três execuções, de 95 a 135 mil registros/s, pico de 313 MB de RSS no worker e consulta ordenada no fim do dataset em 60 a 100 ms. Os runners são compartilhados, então trate como ordem de grandeza; método, ressalvas e reprodução em [docs/benchmark.md](docs/benchmark.md).

Fase 2, medido localmente (Windows, sem infraestrutura): planilha XLSX de 100 mil linhas importada em cerca de 40 s (≈ 2.470 registros/s — cerca de 40 vezes mais lento que o CSV, porque fórmulas e valores são lidos em duas passadas); transformação com quatro regras e deduplicação sobre 100 mil registros em 0,9 a 1,1 s, com a análise de duplicidades do DuckDB conferindo a contagem do pipeline.

Fase 3, no mesmo ambiente: relatório de qualidade de 100 mil registros em 0,19 a 0,28 s; consulta do explorer com filtro, busca e contagem em 0,11 a 0,12 s.

Fase 4, no mesmo ambiente: com 100 mil registros, os KPIs (seis medidas) saem em 0,04 a 0,05 s, a soma por categoria com "Outros" em 0,05 a 0,08 s, a série mensal em 0,05 s e a comparação entre períodos em 0,05 a 0,09 s.

## Limitações conhecidas

- XLSX é lido em Python pelo openpyxl, em duas passadas: ~2,5 mil registros/s na medição local; o progresso mostra só a contagem de registros. A tabela de textos compartilhados da planilha fica inteira em memória.
- A deduplicação carrega a chave de toda a versão em memória; não foi medida acima de 100 mil registros.
- A prévia de transformações usa os primeiros 200 registros; a análise de duplicidades da versão inteira é separada.
- Arredondamento de colunas derivadas é meio-para-par (1,005 → 1,00), diferente do "meio para cima" das planilhas.
- Data Explorer sem download do resultado filtrado: chega com as exportações protegidas da Fase 5 (job assíncrono, expiração, proteção contra formula injection). A busca cobre só colunas de texto.
- Relatórios de qualidade de versões publicadas antes da Fase 3 são calculados sob demanda na tela Qualidade.
- Dashboards: vale a última gravação quando duas pessoas editam o mesmo dashboard; a ordem dos widgets muda pelas setas (sem arrastar e soltar); cada widget é uma consulta ao abrir, sem resultados guardados — medido até 100 mil registros. Decimais não servem como dimensão (use o filtro de faixa).
- Gestão de membros, exportações, auditoria na interface e retenção de arquivos: Fase 5.
- Gráfico da visão geral agrupa por dia em UTC (fuso por workspace chega com as configurações).
- O MinIO Community foi arquivado; o projeto usa a imagem mantida pela Chainguard (ver ADR-006).
- A CI usa a CA interna do Caddy e o Mailpit: certificado público com domínio real e SMTP real com TLS ainda não foram exercitados; ver PROGRESS.md.

## Roadmap

| Fase | Escopo |
| --- | --- |
| 1 ✅ | Fundação, autenticação, workspaces, upload CSV, preview, worker, versão Parquet, explorer paginado |
| 2 ✅ | XLSX e abas, transformações configuráveis, deduplicação, reprocessamento a partir de versões |
| 3 ✅ | Qualidade dos dados (pontuação documentada), Data Explorer com filtros, busca e seleção de colunas |
| 4 ✅ | Dashboards, KPIs, gráficos, filtros dinâmicos, comparação temporal, construtor de dashboards (validação na CI pendente) |
| 5 | Relatórios, exportações CSV/XLSX em segundo plano, gestão de usuários, auditoria, retenção |
| 6 | Testes ampliados, benchmarks com infraestrutura, revisão de segurança e performance, deploy |
