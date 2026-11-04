# Arquitetura

## Visão geral

```mermaid
flowchart TD
    B[Navegador] -->|HTTPS| C[Caddy<br/>SPA estático + proxy reverso]
    C -->|/api, /health| A[FastAPI<br/>uvicorn]
    A -->|metadados, sessões, jobs, auditoria| P[(PostgreSQL 17)]
    A -->|publica tarefas| R[(Redis 8<br/>fila Celery + rate limit)]
    A -->|uploads, leitura de amostra| M[(MinIO / S3<br/>bucket privado)]
    A -->|consultas paginadas| D[DuckDB<br/>em processo, sandbox]
    W[Celery worker] -->|consome| R
    W -->|estado durável, versões| P
    W -->|original ↓ / Parquet ↑| M
    W --> PL[Pipeline<br/>csv + Polars + PyArrow]
    BT[Celery beat] -->|recuperação de jobs| R
    D -->|lê| CACHE[Cache local de Parquet<br/>por versão imutável]
    CACHE -.download sob demanda.- M
```

| Componente | Responsabilidade |
| --- | --- |
| **apps/web** | SPA React + TypeScript. Consome apenas endpoints reais. Nunca mantém o dataset inteiro em memória: só a página atual. |
| **Caddy** | Serve o build estático, aplica CSP e cabeçalhos de segurança, limita corpo de requisição e faz proxy de `/api` e `/health`. HTTPS automático em produção. |
| **FastAPI** | Autenticação, RBAC, validação, upload em streaming, pré-visualização, criação de jobs e consultas. Não executa processamento pesado. |
| **Celery worker** | Executa importações, transformações, exportações (CSV/XLSX) e o envio de e-mails (redefinição de senha, convites). Compartilha modelos, regras e serviços com a API (mesma imagem e mesmo pacote `app`). |
| **Celery beat** | A cada 60 s recupera jobs e exportações interrompidos ou não publicados; a cada 10 min apaga exportações vencidas; a cada 6 h aplica a retenção de originais; uma vez por dia apaga objetos órfãos do armazenamento (ADR-026). |
| **PostgreSQL** | Fonte da verdade: usuários, workspaces, sessões, datasets, colunas, uploads, jobs (estado durável), versões, relatórios de qualidade e dashboards (só a definição dos widgets). |
| **Redis** | Transporte da fila (sem backend de resultados) e contadores de rate limiting. |
| **MinIO (S3)** | Arquivos originais, Parquet das versões e exportações temporárias. Bucket privado; não há URL pública: downloads passam pela API. |
| **DuckDB** | Consultas controladas sobre Parquet: paginação, filtros e busca do explorer, relatório de qualidade e as agregações dos dashboards (KPIs, grupos, séries e comparação entre períodos). |

## Estrutura do repositório

```
apps/web/            SPA (React, Vite, Tailwind, shadcn/ui)
  src/app            providers, router (code splitting por rota), QueryClient
  src/components     componentes compartilhados + ui/ (shadcn)
  src/features       auth, datasets, jobs, transformations, quality, dashboards, admin (exportações, membros, auditoria): API, hooks, componentes de domínio
  src/layouts        layout autenticado (sidebar/topbar) e de autenticação
  src/pages          telas
  src/services       cliente HTTP (CSRF, erros padronizados) e upload com progresso
backend/
  app/api            rotas, dependências (sessão, workspace, RBAC), middlewares, erros
  app/core           configuração, banco, segurança, permissões, rate limit, logs
  app/models         ORM SQLAlchemy 2
  app/schemas        contratos Pydantic da API
  app/repositories   consultas sempre filtradas por workspace
  app/services       casos de uso (auth, upload, preview, importação, transformações, qualidade, análises, dashboards, exportações, membros, retenção, exclusão, jobs, armazenamento)
  app/processing     pipeline puro (sem banco): inspeção, inferência, leitura CSV/XLSX, conversão, regras, escrita de exportações
  app/analytics      DuckDB: consultas filtradas, agregações dos dashboards, relatório de qualidade e cache de Parquet
  app/tasks          Celery (app, tarefas, publicação)
  migrations/        Alembic
  tests/             Pytest
e2e/                 Playwright
docker/              Dockerfiles e Caddyfile
scripts/             gerador de dados sintéticos (CSV e XLSX)
samples/             amostras de 1.000 linhas (as maiores são geradas)
docs/                documentação técnica
```

## Fluxo de uma importação

```mermaid
sequenceDiagram
    participant U as Usuário
    participant API
    participant S3 as MinIO
    participant DB as PostgreSQL
    participant Q as Redis
    participant W as Worker

    U->>API: POST /datasets/upload (corpo binário em streaming)
    API->>API: grava em disco temporário, hash, UTF-8, assinatura, limite de tamanho
    API->>S3: envia original (chave aleatória)
    API->>DB: Dataset (draft) + Upload + auditoria
    U->>API: GET /datasets/{id}/preview
    API->>S3: Range GET (2 MB)
    API-->>U: 20 linhas, tipos inferidos, estatísticas da amostra
    U->>API: POST /datasets/{id}/imports (mapeamento + Idempotency-Key)
    API->>DB: salva mapeamento, cria job (queued) com configuração congelada
    API->>Q: publica imports.run(job_id)
    W->>DB: reivindicação condicional (UPDATE ... WHERE status='queued')
    W->>S3: baixa original e confere SHA-256
    loop a cada lote de 50 mil registros
        W->>W: tokeniza, valida estrutura, converte tipos (Polars), grava Parquet
        W->>DB: progresso (bytes, registros), heartbeat, checa cancelamento
    end
    W->>S3: data.parquet + rejected.parquet
    W->>DB: transação única: versão publicada + dataset.current_version + job succeeded
    U->>API: GET /jobs/{id} (polling enquanto ativo)
    U->>API: GET /datasets/{id}/rows?page=…&sort=…
    API->>API: DuckDB sobre Parquet em cache local
```

Para XLSX, o upload verifica o contêiner e lista as abas; a pré-visualização lê a aba escolhida de uma cópia local em cache (conferida pelo SHA-256), e o worker repete a verificação do contêiner antes de ler. O progresso de XLSX é a contagem de registros (sem percentual).

No frontend, as notificações da barra superior acompanham os últimos jobs do workspace em todas as telas: a cada 3 s enquanto há algum em andamento e a cada 30 s fora disso. `useJobCompletionSync` (`features/jobs/use-job-completion-sync.ts`) entra em ação quando:
- um job visto em andamento termina;
- um job aparece já encerrado entre duas leituras.

Nesses casos, ele invalida as consultas de datasets, análises, dashboards e visão geral. Uma tela aberta durante o processamento (Relatórios, Dashboard geral, Data Explorer, detalhe do dataset) passa a mostrar a versão nova sem ser aberta de novo.

## Fluxo de uma transformação

```mermaid
sequenceDiagram
    participant U as Usuário
    participant API
    participant S3 as MinIO
    participant DB as PostgreSQL
    participant Q as Redis
    participant W as Worker

    U->>API: POST /datasets/{id}/transformation-sets (regras JSON)
    API->>API: valida cada regra contra o esquema da versão atual (plan_rules)
    API->>DB: conjunto + regras (revisão 1)
    U->>API: POST /datasets/{id}/transformations/preview
    API->>S3: Parquet da versão (cache local, SHA-256)
    API-->>U: 200 primeiros registros transformados, excluídos e contagens
    U->>API: POST /datasets/{id}/versions/{vid}/duplicates
    API-->>U: duplicidades da versão inteira (DuckDB GROUP BY)
    U->>API: POST /datasets/{id}/transform-jobs (versão + conjunto + Idempotency-Key)
    API->>DB: job kind=transform, cópia congelada das regras, rows_total da versão
    API->>Q: publica imports.run(job_id)
    W->>S3: baixa o Parquet da versão de origem e confere SHA-256
    loop a cada lote de 50 mil registros
        W->>W: aplica as regras (Polars), separa rejeitados e filtrados
        W->>DB: progresso (registros), heartbeat, checa cancelamento
    end
    W->>W: deduplicação: marca a chave inteira, grava em lotes (se houver)
    W->>S3: data.parquet + rejected.parquet da nova versão
    W->>DB: transação única: versão com parent_version_id + dataset.current_version + job succeeded
```

## Isolamento entre workspaces

- O workspace ativo fica na **sessão do servidor** (`user_sessions.active_workspace_id`), nunca em parâmetro do cliente.
- A cada requisição, `get_context` revalida o pertencimento (`workspace_members`) e lê o papel do banco. Remover um membro tem efeito imediato.
- Toda consulta por ID passa por `repositories/datasets.py`, que filtra por `workspace_id` e responde **404** tanto para recurso inexistente quanto alheio (não revela existência).
- Chaves de armazenamento incluem o workspace, mas o acesso a objetos só acontece pela API após a checagem acima.

## Compartilhamento entre API e worker

Ambos usam a mesma imagem (`docker/api/Dockerfile`) e o mesmo pacote `app`. As regras de conversão vivem em `app/processing` e não dependem de banco nem de rede; `services/job_runner.py` orquestra estado, armazenamento e publicação. Assim a pré-visualização (API) e o processamento (worker) aplicam exatamente as mesmas regras de leitura.
