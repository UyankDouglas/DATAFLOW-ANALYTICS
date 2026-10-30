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
| `SMTP_*` | Servidor SMTP real para e-mails de redefinição de senha. |

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
curl -fsS https://$SITE_ADDRESS/health/ready
```

Ordem de inicialização garantida pelo Compose: `postgres` saudável → `migrate` (Alembic `upgrade head`) → `minio-perms` → `minio` → `storage-setup` (aguarda S3 e cria bucket) → `api`, `worker`, `beat` → `web` (Caddy).

## Atualização

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

As migrations rodam automaticamente no serviço `migrate` antes de API e worker. Migrations destrutivas serão sempre documentadas no changelog com o impacto e o procedimento de backup prévio.

## Escala

- **Workers**: `WORKER_REPLICAS`, `WORKER_CONCURRENCY`, `WORKER_CPUS`, `WORKER_MEMORY`. O processamento é por lotes e cada job usa memória limitada (~40–60 MB por 100 mil linhas medidos, ver `benchmark.md`).
- **API**: stateless (sessões no PostgreSQL); o cache de Parquet é local por contêiner e se recompõe sob demanda.
- **Beat**: manter **uma** instância.

## Backups

| Dado | Como |
| --- | --- |
| PostgreSQL | `docker compose -f docker-compose.prod.yml exec postgres pg_dump -U $POSTGRES_USER -Fc dataflow > backup.dump` (agende diariamente). |
| MinIO | Espelhar o bucket com `mc mirror` para outro destino S3, ou snapshot do volume `miniodata`. |
| Redis | Não é fonte da verdade (fila e rate limit). O estado dos jobs está no PostgreSQL; jobs interrompidos são recuperados. |

Restaure banco e bucket do **mesmo ponto no tempo**: versões referenciam objetos por chave.

## Observabilidade

- Logs JSON em stdout (API, worker, Caddy) — use `docker compose logs` ou um coletor (Loki, Vector).
- `GET /health/live` (processo) e `GET /health/ready` (banco, Redis, armazenamento; 503 se degradado).
- Cada resposta da API inclui `X-Request-ID`, também presente nos logs.

## Alternativas de armazenamento

O backend usa somente a API S3. Para S3 gerenciado, remova os serviços `minio*` e defina `S3_ENDPOINT_URL` (vazio para AWS), `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`.
