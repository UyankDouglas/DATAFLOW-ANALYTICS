# Segurança e privacidade

O sistema recebe arquivos de usuários; segurança é requisito central. Esta página lista o que está implementado na Fase 1 e o que fica para as próximas fases.

## Autenticação e sessão

| Controle | Implementação |
| --- | --- |
| Senhas | Argon2id (`argon2-cffi`, parâmetros RFC 9106 baixo consumo). Rehash automático se os parâmetros mudarem. Mínimo de 10 caracteres, ao menos 4 caracteres distintos, diferente do e-mail. |
| Tempo constante | Login com e-mail inexistente verifica um hash fictício, igualando o tempo de resposta. Mesma mensagem para e-mail ou senha errados. |
| Sessão | Token aleatório de 256 bits no cookie `df_session` (HttpOnly, SameSite=Lax, Secure em produção, 12 h). O banco guarda só o SHA-256. Logout e redefinição de senha revogam no servidor. |
| CSRF | Double-submit assinado: cabeçalho `X-CSRF-Token` = cookie `df_csrf` = `HMAC(SECRET_KEY, hash da sessão)`; antes do login, token anônimo assinado. Verificação de `Origin` contra allowlist. |
| Recuperação de senha | Token de uso único (hash no banco), expira em 30 min, tokens anteriores invalidados. Resposta idêntica exista ou não a conta. E-mail enviado pelo worker (Mailpit em desenvolvimento). |
| Rate limiting | Redis, janela fixa: login por e-mail+IP e por IP, cadastro por IP, recuperação por e-mail e por IP, upload por usuário. Resposta 429 com `Retry-After`. Falha aberta se o Redis cair (ADR-012). |

## Autorização e isolamento

- RBAC no backend (`core/permissions.py`): Administrador, Analista, Visualizador, com permissões explícitas. O frontend só esconde ações; quem decide é o servidor.
- Workspace ativo na sessão do servidor; pertencimento e papel relidos do banco **a cada requisição**.
- Recursos por ID (dataset, versão, job, rejeitados, registros) sempre filtrados por workspace; resposta 404 para inexistente ou alheio.
- Testado: `backend/tests/test_isolation.py` (API) e `e2e/tests/isolation.spec.ts` (interface + API com sessão de outro workspace).

## Uploads

- Extensão em allowlist (`.csv` na Fase 1; `.xlsx` recusado com mensagem até existir suporte real e testado).
- Conteúdo real verificado: assinaturas de ZIP/XLSX, XLS, PDF, executáveis, imagens, GZIP, RAR e 7z; UTF-16; bytes nulos; arquivo vazio.
- Limite aplicado **durante** o recebimento (e no proxy). Arquivos nunca são lidos inteiros em memória.
- Nome interno aleatório; nome original sanitizado apenas para exibição.
- Arquivos temporários removidos em `finally`; tarefa periódica limpa sobras de workers interrompidos.
- Bucket privado, sem URLs públicas; todo acesso passa pela API autorizada.
- Integridade: SHA-256 do original conferido pelo worker; SHA-256 do Parquet conferido ao popular o cache.
- Limites de processamento: campo até 1 MB, até 500 colunas, lotes de 50 mil registros, tempo máximo de tarefa (soft 1 h).

## Consultas

- Não existe SQL, Python ou JavaScript vindo do usuário; não há `eval`.
- Identificadores validados contra o esquema da versão e citados; valores sempre parametrizados.
- DuckDB isolado: sem acesso externo (rede/arquivos fora do cache), configuração travada, 2 threads e 512 MB por consulta, `page_size` máximo 200.

## Erros, logs e cabeçalhos

- Erros padronizados `{"error": {code, message, details}, "request_id"}`; exceções inesperadas viram 500 genérico, com detalhes só no log.
- Logs JSON com `request_id`, método, rota, status e duração. Não registram e-mails, senhas, tokens nem conteúdo de arquivos.
- Auditoria (`audit_logs`): cadastro, login (sucesso e falha), logout, troca de workspace, redefinição de senha, upload aceito/recusado, mudança de configuração, importação solicitada, cancelamento, versão publicada, falha e cancelamento de job.
- Cabeçalhos: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store` na API; CSP restritiva e `Permissions-Policy` no SPA (Caddy).

## Segredos e infraestrutura

- Segredos apenas por variável de ambiente. Em produção a API **não sobe** com `SECRET_KEY` padrão/curta, `COOKIE_SECURE=false` ou senha padrão do S3.
- Contêineres da aplicação rodam como usuário sem privilégios; MinIO (Chainguard) como UID 65532.
- Produção expõe apenas o Caddy (80/443); PostgreSQL, Redis (com senha) e MinIO ficam na rede interna.
- Worker com limites de CPU e memória (`deploy.resources.limits`) e `worker_max_tasks_per_child`.

## Pendências (fases seguintes)

- Proteção contra CSV/Excel formula injection nas **exportações** (Fase 5 — não há exportação na Fase 1).
- Políticas de retenção e exclusão controlada de arquivos e versões (Fase 5).
- XLSX: limites de descompressão (zip bomb), planilhas criptografadas, fórmulas sem valor calculado (Fase 2).
- Limpeza de objetos órfãos quando o commit no banco falha após o envio ao S3 (Fase 5).
- Verificação de e-mail no cadastro e MFA (roadmap).
