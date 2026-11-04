# Deploy

O alvo inicial é um único host Linux com Docker Engine 27+ e Docker Compose v2. Não há dependência de serviços pagos.

## Produção com Docker Compose

```bash
git clone <repo> dataflow-analytics && cd dataflow-analytics
cp .env.example .env
```

Preencha no `.env` (obrigatórios no `docker-compose.prod.yml`):

| Variável | Observação |
| --- | --- |
| `SITE_ADDRESS` | Domínio público (ex.: `dados.suaempresa.com.br`). O Caddy emite o certificado HTTPS automaticamente — o DNS precisa apontar para o host e as portas 80/443 precisam estar abertas. |
| `SECRET_KEY` | ≥ 32 caracteres. `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | Credenciais do banco interno. |
| `REDIS_PASSWORD` | Senha do Redis interno. |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Credenciais do MinIO (também usadas pela API como chave S3). |
| `MINIO_IMAGE` | Recomendado fixar digest: `cgr.dev/chainguard/minio@sha256:…` (ADR-006). |
| `SMTP_*` | Servidor SMTP real para e-mails de redefinição de senha. O `.env.example` traz os valores de desenvolvimento (`localhost:1025`, sem TLS): troque todos. |

Opcionais:

| Variável | Padrão | Observação |
| --- | --- | --- |
| `MAX_CSV_MB`, `MAX_XLSX_MB` | 100, 25 | Tamanho máximo dos uploads. |
| `EXPORT_MAX_ROWS`, `EXPORT_XLSX_MAX_ROWS` | 500 mil, 100 mil | Registros por exportação. |
| `WORKSPACE_STORAGE_QUOTA_MB` | 10240 | Cota de armazenamento por workspace; 0 desliga (ADR-027). |
| `QUERY_CONCURRENCY`, `QUERY_MEMORY_MB` | 2, 512 | Consultas DuckDB simultâneas por processo e memória de cada uma. A memória da API (`API_MEMORY`, 1,5 GB) precisa caber o produto dos dois e o processo (ADR-028). |
| `ORPHAN_GRACE_HOURS` | 24 | Idade mínima de um objeto sem registro antes da limpeza diária (ADR-026). |
| `EXPOSE_API_DOCS` | `false` em produção | `true` publica `/api/docs` e `/api/openapi.json`. |
| `REGISTER_LIMIT_PER_HOUR` | 10 | Cadastros por hora a partir do mesmo IP; a CI eleva o valor só para a suíte E2E, que cria várias contas seguidas. |

As senhas do PostgreSQL e do Redis entram nas URLs de conexão: use apenas caracteres seguros em URL, como hexadecimal (`openssl rand -hex 32`).

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
curl -fsS https://$SITE_ADDRESS/health/ready
```

Ordem de inicialização garantida pelo Compose: `postgres` saudável → `migrate` (Alembic `upgrade head`) → `minio-perms` → `minio` → `storage-setup` (aguarda S3 e cria bucket) → `api`, `worker`, `beat` → `web` (Caddy).

**Redes e privilégios.** Banco, Redis e MinIO ficam na rede `backend`, declarada `internal`: não alcançam a internet. A API também está na rede `edge`, com o Caddy, e o worker na `egress`, para o SMTP. Os contêineres da aplicação e o MinIO rodam sem capabilities, e todos com `no-new-privileges`. O Caddy mantém só `NET_BIND_SERVICE`, para as portas 80 e 443.

### Imagens prontas

Uma tag `v*` publica as imagens no GitHub Container Registry (`.github/workflows/release.yml`). Com elas, o host não precisa compilar nada:

```bash
export BACKEND_IMAGE=ghcr.io/<dono>/dataflow-backend:v1.0.0 WEB_IMAGE=ghcr.io/<dono>/dataflow-web:v1.0.0
docker compose -f docker-compose.prod.yml up -d --no-build
```

O fluxo de publicação ainda não foi executado: nenhuma tag foi criada.

### Dados de demonstração

```bash
DEMO_PASSWORD='uma-senha-forte' python3 scripts/seed_demo.py --base-url https://$SITE_ADDRESS
```

Cria a conta `demo@example.com` (ou a de `--email`) e, pela API, envia e processa os arquivos fictícios de `samples/`, aplica um conjunto de regras às vendas, cria o dashboard "Comercial" e pede uma exportação. Se a conta já tiver datasets, não faz nada.

## O que a CI valida

A cada pull request e push na `main`, o job `docker-prod` segue este guia: cria o `.env` a partir do `.env.example`, gera os segredos e sobe o `docker-compose.prod.yml` com `SITE_ADDRESS=localhost`, em que o Caddy emite o certificado pela própria CA interna. Depois confere:

- todos os serviços saudáveis, o redirecionamento de HTTP para HTTPS e os cookies `Secure`;
- as portas de infraestrutura fechadas e o Redis exigindo senha;
- banco e Redis sem rota para a internet, e a API com saída (controle positivo);
- HSTS no Caddy e `/api/openapi.json` respondendo 404;
- o E2E nesse ambiente;
- **backup e restauração**: conta as linhas das tabelas principais, roda `scripts/backup.sh`, apaga todos os volumes, sobe uma instalação vazia, confere que `scripts/restore.sh` sem `--yes` não altera nada, restaura, compara as contagens e confere cada objeto referenciado pelo banco (tamanho e SHA-256).

O job `benchmark` sobe o Compose de desenvolvimento e roda `scripts/benchmark_stack.py` (ver `benchmark.md`).

Ainda não foram exercitados: certificado público com domínio real, SMTP real com TLS e autenticação, atualização de uma instalação existente com migrations novas (esta fase não tem migration) e a publicação das imagens.

## Atualização

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

As migrations rodam automaticamente no serviço `migrate` antes de API e worker. Migrations destrutivas serão sempre documentadas no changelog com o impacto e o procedimento de backup prévio.

## Escala

- **Workers**: `WORKER_REPLICAS`, `WORKER_CPUS`, `WORKER_MEMORY` e `WORKER_CONCURRENCY`. O processamento é por lotes de 50 mil registros. Referências medidas: pico de cerca de 390 MB de RSS no processo do worker com 100 mil linhas, na CI. Com 1 milhão, o pico do heap Python foi de 43 MB, medido localmente fora de contêiner. As medições de 1 milhão no fluxo completo estão em `benchmark.md`. Confira o uso real antes de reduzir `WORKER_MEMORY`.
- **API**: stateless (sessões no PostgreSQL); o cache de Parquet é local por contêiner e se recompõe sob demanda.
- **Beat**: manter **uma** instância.

## Backups

Banco e objetos precisam ser do **mesmo ponto no tempo**: versões referenciam objetos por chave. `scripts/backup.sh` garante isso parando API, worker, beat e MinIO durante a cópia (o site fica indisponível por alguns segundos a minutos, conforme o volume):

```bash
bash scripts/backup.sh                     # backups/AAAAMMDD-HHMMSS/
```

O diretório recebe `postgres.dump` (`pg_dump -Fc`), `minio.tar.gz` (o volume `miniodata` inteiro), `SHA256SUMS` e `MANIFEST`. Copie-o para fora do host e agende a execução (ex.: cron diário fora do horário de uso).

Para restaurar:

```bash
bash scripts/restore.sh backups/20261103-020000           # só mostra o que faria
bash scripts/restore.sh backups/20261103-020000 --yes
```

**Impacto:** o banco inteiro e todos os objetos são substituídos pelos do backup, e tudo o que foi gravado depois dele é perdido. O script confere os hashes do backup antes de começar, recria cada tabela (`pg_restore --clean`, numa transação), substitui o volume do MinIO, sobe os serviços e roda `python -m app.scripts.verify_storage --deep`. Essa verificação falha se algum objeto referenciado pelo banco faltar ou não conferir.

O Redis não entra no backup: guarda só a fila e o rate limit. O estado dos jobs está no PostgreSQL, e os interrompidos são recuperados.

A CI executa esse ciclo inteiro (backup, apagar os volumes, restaurar e verificar) a cada pull request.

## Observabilidade

- Logs JSON em stdout (API, worker, Caddy) — use `docker compose logs` ou um coletor (Loki, Vector).
- `GET /health/live` (processo) e `GET /health/ready` (banco, Redis, armazenamento; 503 se degradado).
- Cada resposta da API inclui `X-Request-ID`, também presente nos logs.

## Alternativas de armazenamento

O backend usa somente a API S3. Para usar um S3 gerenciado, edite o `docker-compose.prod.yml`: remova os serviços `minio*` e as dependências deles e defina `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` e `S3_BUCKET` no bloco `x-backend`. Essa variação ainda não foi testada.

## Tarefas periódicas

O serviço `beat` precisa estar no ar. Ele recupera processamentos e exportações interrompidos (a cada minuto), apaga exportações vencidas (a cada 10 minutos), aplica a retenção de originais configurada em cada workspace (a cada 6 horas) e apaga objetos órfãos do armazenamento (uma vez por dia, ADR-026). Convites e redefinição de senha dependem do SMTP configurado (`SMTP_*`).
