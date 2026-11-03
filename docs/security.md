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
- Recursos por ID (dataset, versão, job, rejeitados, registros, consultas do explorer, relatórios de qualidade, inconsistências, frequência de valores, conjuntos de regras, prévia, análise de duplicidades e jobs de transformação) sempre filtrados por workspace; resposta 404 para inexistente ou alheio.
- Transformações: Visualizador lê os conjuntos e pode rodar a análise de duplicidades (só leitura, usada também na tela Qualidade); criar, editar, excluir, gerar prévia e aplicar exigem `transformations:manage` (Analista e Administrador).
- Qualidade: qualquer perfil lê relatórios, inconsistências e frequências; calcular ou recalcular um relatório exige `datasets:process`.
- Dashboards: qualquer perfil abre o Dashboard geral, lista e abre dashboards e aplica filtros na tela; criar, editar, reorganizar e excluir exigem `dashboards:manage` (Analista e Administrador). Dashboard, widget, dataset e versão fixada são conferidos contra o workspace da sessão: não é possível criar um dashboard apontando para dataset ou versão alheios (404).
- Testado: `backend/tests/test_isolation.py`, `backend/tests/test_transform_api.py` e `backend/tests/test_dashboards_api.py` (API, inclusive todas as rotas de transformação e de dashboards com sessão de outro workspace) e `e2e/tests/isolation.spec.ts` (interface + API).

## Uploads

- Extensão em allowlist: `.csv` e `.xlsx`. `.xls`, `.xlsm` e `.xlsb` são recusados com orientação (no navegador e no servidor).
- Conteúdo real verificado. **CSV:** assinaturas de ZIP/XLSX, XLS, PDF, executáveis, imagens, GZIP, RAR e 7z; UTF-16; bytes nulos; arquivo vazio. **XLSX**, no upload e de novo no worker, antes de abrir: planilha criptografada (contêiner OLE com `EncryptionInfo` ou entradas ZIP cifradas), XLS legado, ZIP inválido ou sem as partes obrigatórias, mais de 2.000 entradas, mais de 400 MB descompactados, taxa de compressão acima de 200:1 (bomba de descompressão) e macros (`vbaProject.bin`). O `zipfile` não descompacta além do tamanho declarado de cada entrada e confere o CRC.
- Planilhas são abertas em modo somente leitura com `defusedxml` (sem entidades externas nem expansão de entidades). **Fórmulas nunca são calculadas e macros nunca são lidas**: fórmula sem valor salvo rejeita o registro com motivo, em vez de virar dado.
- Limite aplicado **durante** o recebimento (e no proxy): 100 MB para CSV e 25 MB para XLSX, configuráveis. Arquivos nunca são lidos inteiros em memória (exceção documentada: a tabela de textos compartilhados do XLSX).
- Nome interno aleatório; nome original sanitizado apenas para exibição.
- Arquivos temporários removidos em `finally`; tarefa periódica limpa sobras de workers interrompidos.
- Bucket privado, sem URLs públicas; todo acesso passa pela API autorizada.
- Integridade: SHA-256 do original conferido pelo worker; SHA-256 do Parquet conferido ao popular o cache e antes de transformar uma versão; SHA-256 do XLSX conferido ao usar a cópia local da pré-visualização.
- Importar outra aba como dataset copia o objeto no armazenamento: datasets nunca compartilham arquivos.
- Limites de processamento: campo até 1 MB, até 500 colunas, lotes de 50 mil registros, tempo máximo de tarefa (soft 1 h).

## Consultas

- Não existe SQL, Python ou JavaScript vindo do usuário; não há `eval`.
- Transformações são regras JSON de uma lista fechada de operações, validadas por modelos Pydantic (`extra="forbid"`) e conferidas contra o esquema da versão antes de executar; colunas derivadas aceitam só operações enumeradas com coluna ou valor fixo. Regras com operação desconhecida ou campos extras (ex.: `code`, `sql`) são recusadas com 422 e nunca chegam ao motor (`test_code_like_rules_never_reach_the_engine`).
- A análise de duplicidades usa o mesmo DuckDB isolado, com as colunas da chave validadas contra o esquema e citadas.
- Data Explorer (`POST /datasets/{id}/rows/query`): filtros validados por tipo de coluna (mesmos operadores das regras de filtro), valores sempre parametrizados, busca com `contains()` (sem curingas), no máximo 20 filtros, 50 valores por lista, 100 caracteres de busca, 200 registros por página e **10 s por consulta**, interrompida pelo DuckDB ao exceder. Tentativas de injeção em nome de coluna, ordenação, operador ou valor são recusadas com 422 (`test_explorer_rejects_unsafe_or_invalid_queries`).
- Consultas analíticas e widgets (`POST /datasets/{id}/analytics`, `POST /dashboards/{id}/query`): medidas, agregações e granularidades de listas fechadas, validadas por tipo de coluna; filtros com a mesma validação do explorer; valores parametrizados; no máximo 6 medidas, 100 grupos, 1.000 pontos por série e 10 s por consulta. Campos fora do contrato (ex.: `sql`) e agregações desconhecidas são recusados com 422 (`test_api_rejects_out_of_allowlist_requests`); nomes de coluna com aspas ou SQL viram `invalid_metric` (`test_plan_rejects_invalid_queries`). Dashboards guardam só a definição dos widgets, nunca resultados (ADR-021, ADR-022).
- Relatórios de qualidade guardam só agregados no PostgreSQL; valores de texto dos registros (frequências, valor original de inconsistências) são lidos do Parquet sob demanda, após a checagem de workspace (ADR-019).
- Identificadores validados contra o esquema da versão e citados; valores sempre parametrizados.
- DuckDB isolado: sem acesso externo (rede/arquivos fora do cache), configuração travada, 2 threads e 512 MB por consulta, `page_size` máximo 200.

## Erros, logs e cabeçalhos

- Erros padronizados `{"error": {code, message, details}, "request_id"}`; exceções inesperadas viram 500 genérico, com detalhes só no log.
- Logs JSON com `request_id`, método, rota, status e duração. Não registram e-mails, senhas, tokens nem conteúdo de arquivos.
- Auditoria (`audit_logs`): cálculo de relatório de qualidade sob demanda, cadastro, login (sucesso e falha), logout, troca de workspace, redefinição de senha, upload aceito/recusado (com o código do motivo), aba importada como dataset, mudança de configuração, importação e transformação solicitadas, conjunto de regras criado/alterado/excluído, cancelamento, versão publicada (com tipo e versão de origem), falha e cancelamento de job.
- Cabeçalhos: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store` na API; CSP restritiva e `Permissions-Policy` no SPA (Caddy).

## Segredos e infraestrutura

- Segredos apenas por variável de ambiente. Em produção a API **não sobe** com `SECRET_KEY` padrão/curta, `COOKIE_SECURE=false` ou senha padrão do S3.
- Contêineres da aplicação rodam como usuário sem privilégios; MinIO (Chainguard) como UID 65532.
- Produção expõe apenas o Caddy (80/443); PostgreSQL, Redis (com senha) e MinIO ficam na rede interna.
- Worker com limites de CPU e memória (`deploy.resources.limits`) e `worker_max_tasks_per_child`.

## Pendências (fases seguintes)

- Proteção contra CSV/Excel formula injection nas **exportações** (Fase 5 — não há exportação na Fase 1).
- Políticas de retenção e exclusão controlada de arquivos e versões (Fase 5).
- Limpeza de objetos órfãos quando o commit no banco falha após o envio ao S3 (Fase 5).
- Verificação de e-mail no cadastro e MFA (roadmap).
