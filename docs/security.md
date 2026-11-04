# Segurança e privacidade

O sistema recebe arquivos de usuários; segurança é requisito central. Esta página lista os controles implementados, o resultado da revisão de segurança da Fase 6 e o que continua em aberto.

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
- Exportações: pedir, listar e baixar exigem `data:export` (Analista e Administrador; Visualizador só quando o administrador libera nas configurações). Excluir cabe a quem pediu ou a um administrador. Membros, convites, configurações, auditoria e exclusão de datasets e versões são do Administrador (`members:manage`, `workspace:manage`, `audit:view`, `datasets:delete`). O servidor não deixa o workspace sem administrador, e quem é removido perde o acesso na requisição seguinte.
- Dashboards: qualquer perfil abre o Dashboard geral, lista e abre dashboards e aplica filtros na tela; criar, editar, reorganizar e excluir exigem `dashboards:manage` (Analista e Administrador). Dashboard, widget, dataset e versão fixada são conferidos contra o workspace da sessão: não é possível criar um dashboard apontando para dataset ou versão alheios (404).
- Testado: `backend/tests/test_isolation.py`, `test_transform_api.py`, `test_dashboards_api.py`, `test_exports_api.py`, `test_members_api.py` e `test_admin_api.py` (API, inclusive todas as rotas de transformação e de dashboards com sessão de outro workspace) e `e2e/tests/isolation.spec.ts` (interface + API).

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
- Limites de processamento: campo até 1 MB, até 500 colunas, lotes de 50 mil registros, tempo máximo de tarefa (soft 1 h). Planilhas são lidas até a linha 1.048.576 (o limite do Excel; além dela a planilha é recusada) e cada linha só até a coluna 1.024 (ADR-029).
- Cota de armazenamento por workspace (`WORKSPACE_STORAGE_QUOTA_MB`, 10 GB por padrão), conferida antes de ler o corpo e de novo antes de gravar (ADR-027).

## Consultas

- Não existe SQL, Python ou JavaScript vindo do usuário; não há `eval`.
- Transformações são regras JSON de uma lista fechada de operações, validadas por modelos Pydantic (`extra="forbid"`) e conferidas contra o esquema da versão antes de executar; colunas derivadas aceitam só operações enumeradas com coluna ou valor fixo. Regras com operação desconhecida ou campos extras (ex.: `code`, `sql`) são recusadas com 422 e nunca chegam ao motor (`test_code_like_rules_never_reach_the_engine`).
- A análise de duplicidades usa o mesmo DuckDB isolado, com as colunas da chave validadas contra o esquema e citadas.
- Data Explorer (`POST /datasets/{id}/rows/query`): filtros validados por tipo de coluna (mesmos operadores das regras de filtro), valores sempre parametrizados, busca com `contains()` (sem curingas), no máximo 20 filtros, 50 valores por lista, 100 caracteres de busca, 200 registros por página e **10 s por consulta**, interrompida pelo DuckDB ao exceder. Tentativas de injeção em nome de coluna, ordenação, operador ou valor são recusadas com 422 (`test_explorer_rejects_unsafe_or_invalid_queries`).
- Consultas analíticas e widgets (`POST /datasets/{id}/analytics`, `POST /dashboards/{id}/query`): medidas, agregações e granularidades de listas fechadas, validadas por tipo de coluna; filtros com a mesma validação do explorer; valores parametrizados; no máximo 6 medidas, 100 grupos, 1.000 pontos por série e 10 s por consulta. Campos fora do contrato (ex.: `sql`) e agregações desconhecidas são recusados com 422 (`test_api_rejects_out_of_allowlist_requests`); nomes de coluna com aspas ou SQL viram `invalid_metric` (`test_plan_rejects_invalid_queries`). Dashboards guardam só a definição dos widgets, nunca resultados (ADR-021, ADR-022).
- Relatórios de qualidade guardam só agregados no PostgreSQL; valores de texto dos registros (frequências, valor original de inconsistências) são lidos do Parquet sob demanda, após a checagem de workspace (ADR-019).
- Identificadores validados contra o esquema da versão e citados; valores sempre parametrizados.
- DuckDB isolado: sem acesso externo (rede/arquivos fora do cache), configuração travada, 2 threads e 512 MB por consulta, `page_size` máximo 200, no máximo 2 consultas simultâneas por processo (503 `query_busy` depois de 10 s de espera, ADR-028).

## Erros, logs e cabeçalhos

- Erros padronizados `{"error": {code, message, details}, "request_id"}`; exceções inesperadas viram 500 genérico, com detalhes só no log.
- Logs JSON com `request_id`, método, rota, status e duração. Não registram e-mails, senhas, tokens nem conteúdo de arquivos. As tarefas de e-mail publicam `argsrepr` sem endereço nem token, e o formatador omite os argumentos que o Celery anexa às falhas. O Caddy troca o parâmetro `token` da URL e do `Referer` por `REDACTED` no log de acesso. A CI confere os logs depois do E2E de convite e de redefinição de senha.
- Auditoria (`audit_logs`): cálculo de relatório de qualidade sob demanda, cadastro, login (sucesso e falha), logout, troca de workspace, redefinição de senha, upload aceito/recusado (com o código do motivo), aba importada como dataset, mudança de configuração, importação e transformação solicitadas, conjunto de regras criado/alterado/excluído, cancelamento, versão publicada (com tipo e versão de origem), falha e cancelamento de job.
- Cabeçalhos: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` na API; CSP restritiva, `Permissions-Policy`, `Referrer-Policy: no-referrer` (os links de convite e redefinição levam o token na URL) e HSTS (`max-age=31536000`) no SPA (Caddy).
- Documentação interativa da API (`/api/docs`, `/api/openapi.json`) desligada em produção, salvo `EXPOSE_API_DOCS=true`.

## Segredos e infraestrutura

- Segredos apenas por variável de ambiente. Em produção a API **não sobe** com `SECRET_KEY` padrão/curta, `COOKIE_SECURE=false` ou senha padrão do S3.
- Contêineres da aplicação rodam como usuário sem privilégios; MinIO (Chainguard) como UID 65532.
- Produção expõe apenas o Caddy (80/443). PostgreSQL, Redis (com senha) e MinIO ficam na rede `backend`, declarada `internal` (sem saída para a internet). A API tem uma segunda rede para o Caddy, e o worker, outra para o SMTP.
- Contêineres da aplicação e o MinIO sem nenhuma capability (`cap_drop: [ALL]`), todos com `no-new-privileges`. O Caddy fica só com `NET_BIND_SERVICE`.
- API e worker com limites de CPU, memória e processos (`deploy.resources.limits`) e `worker_max_tasks_per_child`.

## Exportações, convites, retenção e exclusão

- **Formula injection**: texto iniciado por `=`, `+`, `-`, `@`, tabulação, CR ou as variantes de largura total recebe um apóstrofo nas exportações CSV e XLSX; no XLSX, a célula de texto é gravada com o tipo texto e caracteres de controle são removidos (`test_export_writers.py`, `test_xlsx_export_neutralizes_formulas`).
- **Exportações**: volume conferido antes de enfileirar (500 mil registros em CSV, 100 mil em XLSX, 3 em andamento por workspace); arquivo no MinIO privado, chave sem texto do usuário, nome de download ASCII montado pelo backend; download transmitido pela API com `no-store` e auditoria; expiração (24 h por padrão) com remoção do arquivo (ADR-023).
- **Convites**: só o hash do token no banco, validade de 7 dias, uso único, aceitar exige o mesmo e-mail da sessão, limite de 50 convites por hora por workspace (ADR-024).
- **Retenção**: originais apagados após o prazo configurado, nunca os de datasets sem versão ou em processamento; versões ficam (ADR-025).
- **Exclusão controlada**: impacto mostrado antes, confirmação pelo nome, bloqueio com processamento ou exportação em andamento e com versão fixada por dashboard; banco limpo numa transação e objetos removidos depois (ADR-025).

- **Objetos órfãos**: varredura diária apaga do MinIO só chaves geradas pelo sistema, sem registro no banco, fora de processamento ou exportação em andamento e com mais de 24 h (ADR-026).

## Dependências

- **Backend (Python), na CI**: o último passo do job do backend exporta do `uv.lock` as dependências que vão para a imagem, com `uv export --frozen --no-dev --no-emit-project`. O `pip-audit` 2.10.1, em versão fixa e executado pelo `uvx`, consulta cada pacote na base OSV, que reúne os avisos da PyPA (PYSEC) e do GitHub (GHSA).
  - Qualquer vulnerabilidade conhecida falha o job. Os jobs de Compose e o benchmark dependem dele e, nesse caso, não rodam.
  - Com `--strict`, um pacote que não pode ser auditado também falha o job.
  - Os marcadores de ambiente são avaliados como no contêiner (Linux, CPython 3.13).
  - As dependências de desenvolvimento ficam de fora, como no `pnpm audit --prod`, porque não entram na imagem (`uv sync --frozen --no-dev` no Dockerfile).
- **Frontend**: `pnpm audit --prod`, rodado localmente. Não encontrou vulnerabilidades conhecidas em 03/11/2026. Ainda não roda na CI.
- **Quando aparecer uma vulnerabilidade**:
  1. Atualizar o pacote no `uv.lock` (`uv lock --upgrade-package <pacote>`).
  2. Rodar a suíte do backend (`uv run pytest --cov=app`).
  3. Registrar a mudança no `PROGRESS.md`.

  Ignorar um aviso (`--ignore-vuln <ID>` no passo da CI) só com a justificativa aqui: o ID, por que o código não é afetado e quando rever. Hoje nenhum aviso é ignorado.
- **Resultado em 04/11/2026**: nenhuma vulnerabilidade conhecida nos 61 pacotes de produção, nas bases OSV e PyPI. O `uv.lock` não precisou mudar.
- **Para rodar localmente**:

  ```bash
  cd backend
  uv export --frozen --no-dev --no-emit-project --format requirements.txt --output-file /tmp/requirements-audit.txt
  uvx --python 3.13 pip-audit@2.10.1 -r /tmp/requirements-audit.txt --disable-pip --strict --vulnerability-service osv
  ```

  No Windows, o marcador do `uvloop` (`sys_platform != 'win32'`) o tira da conta. Na CI, ele é auditado.

## Revisão de segurança da Fase 6

Feita por um revisor independente, só leitura, sobre o código inteiro, os Dockerfiles, os Compose e o Caddyfile. Cada achado foi conferido no código antes da correção:

| Gravidade | Achado | Correção | Evidência |
| --- | --- | --- | --- |
| Alta | Uma planilha de 2 KB com uma linha `r="999999999999"` fazia o leitor gerar uma linha vazia por índice faltante: a pré-visualização (aberta a qualquer perfil) não terminava, e cerca de 20 pedidos esgotavam as conexões da API para todos os workspaces | Leitura até a linha 1.048.576, com recusa da planilha além disso; exame de cada linha até a coluna 1.024 | `test_row_index_beyond_excel_limit_is_rejected_quickly`, `test_cells_far_to_the_right_are_capped_and_flagged` |
| Média | Endereço e token dos e-mails de convite e redefinição apareciam no log do Celery quando o envio falhava; o token da URL ia para o log de acesso do Caddy e para o `Referer` | `argsrepr` sem dados, formatador sem `args`/`kwargs`, filtro do Caddy, `Referrer-Policy: no-referrer` | `test_email_tasks_never_expose_address_or_token_in_task_logs`, `test_log_formatter_scrubs_task_arguments`, passo "Logs sem tokens nem e-mails" da CI |
| Média | Sem verificação de e-mail no cadastro, quem obtém o link de um convidado ainda sem conta pode criá-la e aceitar; a ADR-024 dizia o contrário | ADR-024 corrigida; o vazamento pelos logs foi fechado | — (verificação de e-mail segue no roadmap) |
| Média | Sem cota, uma conta podia encher o disco compartilhado com o banco | Cota por workspace (ADR-027) | `test_storage_quota_blocks_uploads_and_sheet_copies`, `test_quota_uses_the_real_size_when_content_length_is_missing` |
| Baixa/média | Consultas DuckDB simultâneas sem teto podiam passar da memória da API; a análise de duplicidades não tinha tempo-limite | Teto por processo e tempo-limite (ADR-028) | `test_duckdb_queries_share_a_bounded_number_of_slots` |
| Baixa | Sem HSTS; `/api/docs` em produção; contêineres com todas as capabilities e com saída para a internet | HSTS, docs desligadas, `cap_drop`, `no-new-privileges`, rede `internal` (ADR-029) | `test_api_docs_are_off_in_production_unless_requested`, passos "HSTS…" e "Banco, Redis e MinIO sem saída" da CI |

Conferidos e sem problema: isolamento por workspace em todas as rotas, CSRF em todos os métodos não seguros, sessões geradas pelo servidor e revogadas no logout e na redefinição, chaves e caminhos montados só com UUIDs, nome de download restrito a `[a-z0-9_-]`, sandbox do DuckDB, identificadores validados e valores parametrizados, neutralização de fórmulas, erros 500 genéricos, verificações do ZIP e `defusedxml`.

## Pendências

- Verificação de e-mail no cadastro e MFA (roadmap). Até lá, o link do convite vale como prova de posse do e-mail (ADR-024).
- Credenciais dedicadas: a API e o worker usam as credenciais raiz do MinIO e o usuário criado pelo contêiner do PostgreSQL (superusuário). O Caddy roda como root, só com `NET_BIND_SERVICE`.
- Sistema de arquivos somente leitura nos contêineres (`read_only`) não foi aplicado: exige mapear cada diretório de escrita (cache, temporários, agenda do beat).
- Auditoria das dependências do frontend na CI: `pnpm audit --prod` só roda localmente. As do backend são auditadas a cada pull request e push na `main` (ver "Dependências").
