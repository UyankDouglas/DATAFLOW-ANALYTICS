# Relatórios, exportações e administração

A Fase 5 entrega a tela Relatórios, as exportações CSV e XLSX em segundo plano, a gestão de membros com convites por e-mail, a auditoria consultável, as configurações do workspace, a retenção de arquivos originais e a exclusão controlada de datasets e versões.

## Relatórios

A tela **Relatórios** usa o mesmo motor das análises dos dashboards (`analytics/aggregate.py`, ver [dashboards.md](dashboards.md)). A pessoa escolhe:

- dataset e versão;
- agrupamento: nenhum (só totais), uma categoria ou uma data com granularidade;
- até 6 medidas;
- os filtros da tela;
- uma comparação entre períodos.

A tabela mostra até 100 grupos. A exportação do relatório leva até **10 mil grupos**; os que passarem disso vão somados em "Outros".

## Exportações

| Tipo | O que sai | Onde se pede |
| --- | --- | --- |
| Registros (`rows`) | Dados tratados da versão, com os filtros, a busca, as colunas e a ordenação da tela | Data Explorer, Relatórios ("Exportar registros") |
| Relatório (`report`) | A tabela do relatório: grupo, medidas e, com comparação, valor anterior e variação (%) | Relatórios ("Exportar relatório") |

**Fluxo:**

1. `POST /exports` valida colunas, filtros e consulta contra o esquema da versão. Para registros, conta quantos sairiam e recusa acima do limite, antes de enfileirar.
2. Cria um `ExportJob` com a consulta e a versão congeladas, registra `export.requested` na auditoria e publica a tarefa `exports.run` no Celery.
3. O worker reivindica a exportação com uma atualização condicional, como os processamentos (ADR-001). Ele lê o Parquet em lotes de 5 mil registros, escreve o arquivo com memória constante, envia ao MinIO e marca a validade.
4. A tela **Exportações** mostra o histórico e se atualiza sozinha enquanto houver arquivo sendo gerado. O download (`GET /exports/{id}/download`) passa pela API, depois da checagem de workspace e permissão, com `Cache-Control: no-store`. Cada download vai para a auditoria.
5. Ao vencer, o beat apaga o arquivo (a cada 10 minutos) e marca a exportação como expirada; o registro fica no histórico. A validade padrão é de 24 horas e vai de 1 a 168 nas configurações.

**Formatos:**

| Formato | Detalhes |
| --- | --- |
| CSV para Excel em português | ponto e vírgula, vírgula decimal, datas dd/mm/aaaa, booleanos Sim/Não, UTF-8 com BOM |
| CSV padrão | vírgula, ponto decimal, datas ISO, `true`/`false`, UTF-8 |
| XLSX | números, datas e booleanos tipados, com formato brasileiro de exibição; texto sempre como texto |

**Formula injection.** Texto que começa com `=`, `+`, `-`, `@`, tabulação, retorno de carro ou as variantes de largura total desses sinais recebe um apóstrofo na frente, como recomenda a OWASP. No XLSX, toda célula de texto é ainda gravada com o tipo texto, então nunca vira fórmula, e caracteres de controle inválidos no XML são removidos. Colunas numéricas saem como número: `-5` continua número. Cabeçalhos passam pela mesma proteção.

**Limites** (variáveis de ambiente):

| Limite | Padrão | Variável |
| --- | --- | --- |
| Registros por CSV | 500 mil | `EXPORT_MAX_ROWS` |
| Registros por XLSX | 100 mil | `EXPORT_XLSX_MAX_ROWS` |
| Grupos por relatório | 10 mil | — |
| Exportações em andamento por workspace | 3 | `EXPORT_ACTIVE_PER_WORKSPACE` |

Medido com 100 mil registros: CSV em cerca de 2 s; XLSX em 23 a 28 s, porque o openpyxl escreve célula por célula em Python. Para volumes grandes, prefira CSV.

**Nomes e armazenamento.** O arquivo fica em `workspaces/{workspace}/exports/{id}/arquivo.{csv|xlsx}`; a chave nunca usa texto do usuário. O nome sugerido no download é ASCII, montado pelo backend: `vendas_v1_registros_20261103-1952.csv`, com horário em UTC.

**Quem exporta.** Analistas e Administradores têm `data:export`. Visualizadores só exportam quando um administrador liga "Visualizadores podem exportar" nas configurações; a permissão passa a valer para eles na próxima requisição. Ver e baixar o histórico exige a mesma permissão. Excluir uma exportação cabe a quem pediu ou a um administrador.

**Falhas.** Uma falha passageira do armazenamento devolve a exportação à fila; o Celery tenta de novo, até 3 vezes. Exportações interrompidas ou cuja publicação na fila se perdeu são reenfileiradas pelo beat a cada minuto.

## Membros e convites

- **Convites por e-mail**: o administrador informa e-mail e perfil.
  - O banco guarda só o SHA-256 do token. O e-mail sai pelo worker (Mailpit em desenvolvimento) com um link válido por 7 dias (`INVITATION_TTL_DAYS`).
  - Reenviar um convite substitui o anterior; convidar quem já é membro é recusado. Há limite de 50 convites por hora por workspace.
- **Aceitar**: o link abre `/convite`. Ali a pessoa entra ou cria a conta e volta à mesma página.
  - Só a conta com o **mesmo e-mail** do convite consegue aceitar. O perfil vem do convite, nunca do cliente, e a sessão já muda para o workspace.
- **Perfis**: o administrador muda o perfil e remove membros. O servidor recusa rebaixar ou remover o **último administrador**.
  - Quem é removido perde o acesso na requisição seguinte, porque o pertencimento é relido a cada requisição, e o workspace ativo das sessões dessa pessoa é limpo.

## Auditoria

`GET /audit` (só Administrador) lista as ações do workspace, da mais recente para a mais antiga. Filtra por ação exata (`export.downloaded`) ou categoria (`export`) e por período, com paginação. Ações registradas:

- acesso, convites e mudanças de membros;
- uploads e processamentos;
- qualidade e dashboards;
- exportações (pedido, download e exclusão);
- configurações;
- retenção e exclusões.

Os registros guardam ids, contagens e parâmetros técnicos, sem conteúdo de arquivos nem senhas. O IP aparece para administradores, como dado de segurança.

## Configurações

`PATCH /workspaces/current` (só Administrador) altera:

- o nome do workspace;
- a validade das exportações;
- a exportação por visualizadores;
- a retenção dos originais.

Cada alteração vai para a auditoria com o valor anterior e o novo.

## Retenção dos arquivos originais

Com `original_retention_days` definido (7 a 3.650 dias), o beat apaga a cada 6 horas os originais enviados há mais tempo que isso. A tela avisa no detalhe do dataset, e cada original apagado vai para a auditoria.

| O que continua | O que deixa de existir |
| --- | --- |
| Versões publicadas (consultar, transformar, exportar e usar em dashboards) | A pré-visualização e o reprocessamento daquele arquivo do zero (`original_purged`, 410) |

Nunca é apagado o original de um dataset sem versão publicada, nem o de um upload usado por um processamento em andamento.

## Exclusão controlada

**Dataset** (`DELETE /datasets/{id}`, só Administrador):

1. A tela mostra o impacto calculado pela API: versões, arquivos, processamentos, exportações, dashboards e espaço liberado.
2. Para confirmar, a pessoa digita o nome do dataset.
3. A API recusa enquanto houver processamento ou exportação em andamento.
4. O banco é limpo numa transação, em ordem explícita, porque jobs e uploads são referenciados com `RESTRICT`. Depois do commit, os arquivos do dataset e das exportações são apagados do MinIO, e o cache local da API também.

**Versão** (`DELETE /datasets/{id}/versions/{vid}`):

- Recusada quando é a única versão, quando um dashboard a fixou (a mensagem cita qual) ou quando há processamento ou exportação em andamento.
- Se era a versão atual, a anterior mais recente passa a ser a atual.
- Versões derivadas perdem a referência de origem; a linhagem registrada no JSON da versão continua.
- As exportações da versão e o relatório de qualidade saem junto.

Se a limpeza do armazenamento falhar depois do commit, sobram objetos órfãos. Eles ficam sem referência e sem rota que os alcance, e o erro vai para o log.

## API

| Método | Rota | Permissão |
| --- | --- | --- |
| POST · GET | `/exports` | `data:export` |
| GET · DELETE | `/exports/{id}` | `data:export` (excluir: quem pediu ou administrador) |
| GET | `/exports/{id}/download` | `data:export` |
| GET | `/workspaces/current/settings` | todos |
| PATCH | `/workspaces/current` | `workspace:manage` |
| PATCH · DELETE | `/workspaces/current/members/{id}` | `members:manage` |
| GET · POST | `/workspaces/current/invitations` | `members:manage` |
| DELETE | `/workspaces/current/invitations/{id}` | `members:manage` |
| POST | `/invitations/preview` · `/invitations/accept` | link do convite (aceitar exige sessão) |
| GET | `/audit` · `/audit/actions` | `audit:view` |
| GET | `/datasets/{id}/deletion-impact` · `/datasets/{id}/versions/{vid}/deletion-impact` | `datasets:delete` |
| DELETE | `/datasets/{id}` · `/datasets/{id}/versions/{vid}` | `datasets:delete` |
