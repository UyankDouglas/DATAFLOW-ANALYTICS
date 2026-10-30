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
