# Pipeline de dados

Regras de conversão versionadas em `RULES_VERSION = 2.0.0` (`backend/app/processing/types.py`). Cada versão de dataset registra a versão das regras com que foi produzida. Versões da Fase 1 continuam registradas como `1.0.0`.

Dois tipos de processamento geram versões:

- **Importação** (`kind = "import"`): arquivo enviado (CSV ou XLSX) → versão.
- **Transformação** (`kind = "transform"`): versão publicada → nova versão, aplicando um conjunto de regras.

## Etapas

| Etapa | Onde | O que acontece |
| --- | --- | --- |
| **Upload** | API (`services/upload_service.py`) | Corpo em streaming → disco temporário; extensão permitida (`.csv`, `.xlsx`; `.xls`, `.xlsm` e `.xlsb` recusados com orientação); limite por formato aplicado durante o recebimento (100 MB CSV, 25 MB XLSX, configuráveis); SHA-256. **CSV:** assinaturas binárias e UTF-16 recusados, bytes nulos recusados, validação UTF-8 incremental, contagem de quebras de linha, detecção de delimitador e separadores numéricos. **XLSX:** verificação do contêiner (abaixo) e listagem das abas. Envio ao S3 com chave aleatória. |
| **Validação** | API | Arquivo vazio, binário, malformado ou com conteúdo incompatível com a extensão é recusado com código de erro e auditoria (sem conteúdo). |
| **Pré-visualização** | API (`services/preview_service.py`) | **CSV:** lê só os primeiros 2 MB (Range GET). **XLSX:** baixa a planilha para um cache local (chave = id do upload, conferido pelo SHA-256) e lê a aba escolhida em modo somente leitura. Mostra 20 linhas, infere tipos sobre até 1.000 registros e calcula nulos, distintos, linhas vazias e registros com campos a mais/menos **da amostra**. |
| **Mapeamento** | API (`services/import_service.py`) | Valida nome único (sem diferenciar maiúsculas), prefixo reservado `__df_`, formatos permitidos, escala decimal, correspondência com o cabeçalho atual, encoding confirmado (CSV), confirmação explícita de datas ambíguas e o **valor para vazios** de cada coluna (precisa converter para o tipo escolhido). Salva o mapeamento no dataset (reutilizável). |
| **Importação assíncrona** | Worker (`services/job_runner.py`) | Reivindica o job, baixa o original, confere o SHA-256, repete a verificação do contêiner XLSX e executa o pipeline em lotes. |
| **Transformação assíncrona** | Worker | Baixa o Parquet da versão de origem, confere o SHA-256 registrado na publicação, valida as regras contra o esquema dessa versão e aplica-as em lotes; a deduplicação, se houver, roda numa segunda passada. |
| **Armazenamento versionado** | Worker | `data.parquet` (válidos, tipados) e `rejected.parquet` (todo registro que não entrou na versão, com categoria, motivo, regra, coluna, detalhe e valores de entrada em texto). Publicação em uma única transação. |

## Leitura de XLSX

Implementação em `backend/app/processing/xlsx.py`, com openpyxl em modo somente leitura e `defusedxml` ativo (bloqueia entidades XML externas e expansão de entidades).

**Antes de abrir a planilha** (`check_container`), no upload e de novo no worker:

| Verificação | Código |
| --- | --- |
| Contêiner OLE com o fluxo `EncryptionInfo` (planilha protegida por senha) ou entradas ZIP com o bit de criptografia | `xlsx_encrypted` |
| Contêiner OLE sem criptografia (XLS legado) | `xlsx_legacy_format` |
| Não é ZIP, ZIP corrompido, ou faltam `[Content_Types].xml`/`xl/workbook.xml` | `xlsx_invalid` |
| Mais entradas internas que o permitido (2.000) | `xlsx_too_complex` |
| Soma descompactada acima de 400 MB, ou taxa de compressão acima de 200:1 em entrada com mais de 1 MB | `xlsx_decompression_limit` |
| `vbaProject.bin` presente (macros) | `xlsx_macros` |
| Nenhuma aba de dados | `xlsx_no_sheets` |

**O que é lido de cada célula:**

- **Fórmulas nunca são executadas.** A planilha é aberta duas vezes (valores salvos e fórmulas). Fórmula com valor salvo entra pelo valor; fórmula **sem** valor salvo (arquivos gerados por bibliotecas que não calculam) rejeita o registro com `formula_sem_valor`. Células de erro (`#DIV/0!`, `#N/D`, `#REF!`…) rejeitam com `erro_na_celula`.
- Números entram como texto canônico com ponto decimal (`1234.56`), na menor representação exata; o mapeamento converte para o tipo escolhido.
- Datas entram como `aaaa-mm-dd`; com horário (ou formato de célula com horas) como `aaaa-mm-dd hh:mm:ss`.
- Booleanos entram como `true`/`false`.

**Intervalo de dados e cabeçalho.** As dimensões declaradas no arquivo são ignoradas (`reset_dimensions`), porque costumam estar erradas. Sem linha informada, o cabeçalho é a primeira linha "larga" entre as 50 primeiras: com mais da metade das colunas da tabela preenchidas. Isso pula títulos e notas acima da tabela. O usuário pode escolher a linha manualmente. As colunas lidas vão da primeira à última célula preenchida da linha do cabeçalho; valores fora desse intervalo contam como campos a mais.

**Linhas vazias.** Entre registros, viram `linha_vazia` (como no CSV). Ao final da aba, não são registros: são ignoradas e o job registra um aviso com a quantidade.

**Abas.** Cada processamento lê uma aba. Outra aba da mesma planilha pode virar um dataset independente (`POST /datasets/{id}/sheets`), com cópia própria do arquivo no armazenamento.

**Memória.** A aba é lida em streaming, mas o openpyxl carrega a tabela de textos compartilhados (`sharedStrings.xml`) inteira em memória. Uma planilha de 25 MB com muitos textos distintos usa bem mais memória que um CSV do mesmo tamanho; por isso o limite de XLSX é menor e o descompactado é limitado.

## Tipos e regras de conversão

| Tipo | Polars / Parquet | Regra |
| --- | --- | --- |
| Texto | `String` / `string` | Preservado como recebido na importação (sem trim). |
| Inteiro | `Int64` / `int64` | Após remover separador de milhar: `^[+-]?\d+$`; overflow de 64 bits rejeita. |
| Decimal | `Decimal(38, s)` / `decimal128(38, s)` | Separadores configurados; `^[+-]?(\d+(\.\d*)?|\.\d+)$`; mais de `s` casas → rejeição (sem arredondar). |
| Data | `Date` / `date32` | Formato explícito da allowlist (`dd/mm/aaaa`, `aaaa-mm-dd`, …). |
| Data e hora | `Datetime(us)` / `timestamp[us]` | Formato explícito; sem fuso (valor como registrado). |
| Booleano | `Boolean` / `bool` | `true/verdadeiro/sim/s/yes/y/1` e `false/falso/não/nao/n/no/0`, sem diferenciar maiúsculas. |

**Inferência** (amostra): booleano → inteiro → decimal → data → data e hora → texto. Valores numéricos com zeros à esquerda (CEP, matrícula, SKU) ficam como **texto** e geram aviso. Datas que servem a mais de um formato (ex.: `01/02/2024`) são marcadas como **ambíguas** e exigem confirmação antes do processamento. Valores nulos padrão: `""`, `NULL`, `null` (configurável).

**Coluna obrigatória e valor para vazios** (mapeamento da importação). Um valor nulo (vazio ou listado como nulo) em coluna obrigatória rejeita o registro com `campo_obrigatorio`. Se a coluna tiver valor para vazios, ele é aplicado antes, já convertido para o tipo da coluna; o valor é informado no formato canônico (`2025-01-31`, `2025-01-31 08:00:00`, `10.5`, `true`), independente do formato do arquivo.

## Transformações

Implementação em `backend/app/processing/transforms.py`. As regras são JSON validado por modelos Pydantic de uma lista fechada de operações (`extra="forbid"`); não existe expressão livre, SQL, Python ou JavaScript em nenhuma delas. Antes de executar, `plan_rules` confere cada regra contra o esquema que ela vai encontrar (depois das anteriores): colunas existentes, tipos compatíveis, formatos permitidos, nomes novos válidos e únicos, literais convertíveis. Um erro informa a posição da regra.

| Operação | O que faz | Exige | Exclui registro com |
| --- | --- | --- | --- |
| `trim` | Remove espaços do início e do fim; opcionalmente reduz espaços repetidos internos. | texto | — |
| `normalize_text` | Normaliza Unicode (NFKC ou NFC) e, opcionalmente, remove acentos. | texto | — |
| `change_case` | MAIÚSCULAS, minúsculas ou Iniciais Maiúsculas. | texto | — |
| `convert_type` | Converte entre tipos permitidos (texto ↔ qualquer; inteiro ↔ decimal; data ↔ data e hora; booleano ↔ texto). Decimal → inteiro só sem casas; data e hora → data só sem horário; escala menor só sem perda. | — | `tipo_invalido`, `casas_decimais_excedidas` |
| `standardize_dates` | Lê datas em até 6 formatos (testados em ordem) e grava um tipo data ou data e hora. | texto | `tipo_invalido` |
| `fix_numbers` | Interpreta números locais: remove moeda (`R$`, `US$`, `€`, `£`, `$`), separadores configurados, parênteses como negativo. | texto | `tipo_invalido`, `casas_decimais_excedidas` |
| `handle_nulls` | Preenche nulos com valor fixo (convertido para o tipo) ou rejeita o registro. | — | `valor_nulo` |
| `remove_empty_rows` | Descarta registros com todas as colunas nulas ou vazias. | — | `linha_vazia` |
| `filter_rows` | Mantém registros que atendem às condições (todas ou qualquer). Operadores por tipo: texto (igual, diferente, contém, começa/termina com, está em, nulo), números e datas (comparações, entre, está em, nulo), booleano (verdadeiro, falso, nulo). Texto pode ignorar maiúsculas. | — | `removido_por_filtro` (categoria *filtrado*) |
| `rename_columns` | Renomeia colunas; os nomes seguem as regras do mapeamento. | — | — |
| `derived_column` | Nova coluna: operação entre números (+ − × ÷ com escala de saída), concatenação de textos (nulos são ignorados), parte de data (ano, mês, dia, trimestre, dia da semana, ano-mês) ou dias entre duas datas. | tipos compatíveis | `divisao_por_zero` |
| `deduplicate` | Remove registros repetidos pela chave (todas as colunas ou as escolhidas), mantendo o primeiro ou o último. Precisa ser a última regra ativa. | — | `registro_duplicado` (categoria *duplicado*) |

A identificação de duplicidades sem remover nada é a análise da versão inteira (abaixo).

**Precisão.** Operações entre decimais usam escala de trabalho maior que a de saída e o resultado é ajustado à escala pedida com arredondamento meio-para-par (1,005 → 1,00; 1,015 → 1,02). Divisão por zero não vira infinito nem nulo silencioso: rejeita o registro. Nada passa por ponto flutuante.

**Ordem e exclusões.** As regras rodam na ordem salva; regras desativadas ficam no conjunto, mas não executam. Um registro sai da versão na primeira regra que o exclui e fica registrado uma única vez, com a regra (posição 1-based), o motivo, a coluna e os valores de entrada da versão de origem.

### Deduplicação

- **Chave:** todas as colunas ou as escolhidas; nulos contam como iguais entre si.
- **Execução:** segunda passada sobre o resultado inteiro da primeira passada (não por lote), com `is_first_distinct`/`is_last_distinct` do Polars sobre a chave. Cada duplicado registra `__df_duplicate_of`, o número do registro mantido.
- **Análise sem alterar dados:** `POST /datasets/{id}/versions/{vid}/duplicates` conta, na versão inteira, registros duplicados, chaves distintas, chaves repetidas e as 20 chaves mais repetidas (DuckDB `GROUP BY`, que também agrupa nulos juntos). A suíte confere que a análise e o job contam o mesmo (`test_preview_reconciles_sample_and_matches_full_duplicate_analysis`).
- **Prévia:** a prévia de transformações deduplica só a amostra (primeiros 200 registros) e avisa isso na tela.

## Reconciliação

```
recebidos = válidos + rejeitados + filtrados + duplicados
```

- **Recebidos**: na importação, todos os registros após o cabeçalho, inclusive linhas vazias e malformadas; na transformação, os registros da versão de origem.
- **Válidos**: publicados na versão (`data.parquet`).
- **Rejeitados**: problema de dado (estrutura, tipo, obrigatoriedade, célula, nulo, divisão por zero).
- **Filtrados**: não atendem a um filtro configurado.
- **Duplicados**: removidos pela deduplicação. Política explícita: `removidos_dos_validos` — um duplicado removido nunca conta como válido. Quando não há regra de deduplicação, `duplicates` é `null` e a política é `nao_aplicada`.

Cada registro está em exatamente uma categoria. Se a igualdade não fechar, o job falha com `reconciliacao` e nada é publicado. Na transformação, o total lido também precisa bater com o total registrado na versão de origem.

### Códigos de exclusão

| Código | Categoria | Significado |
| --- | --- | --- |
| `linha_vazia` | rejeitado | Registro sem nenhum valor preenchido. |
| `campos_a_menos` / `campos_a_mais` | rejeitado | Quantidade de campos diferente do cabeçalho (o detalhe informa quantos). |
| `csv_malformado` | rejeitado | Aspas malformadas ou campo acima do limite (1 MB). |
| `formula_sem_valor` | rejeitado | Célula de fórmula sem valor calculado salvo no XLSX. |
| `erro_na_celula` | rejeitado | Célula de erro do Excel (`#DIV/0!`, `#N/D`…). |
| `tipo_invalido` | rejeitado | Valor não converte para o tipo configurado (detalhe cita tipo e formato). |
| `casas_decimais_excedidas` | rejeitado | Mais casas decimais que a escala configurada. |
| `campo_obrigatorio` | rejeitado | Coluna obrigatória vazia, sem valor para vazios. |
| `valor_nulo` | rejeitado | Regra "tratar nulos" configurada para rejeitar. |
| `divisao_por_zero` | rejeitado | Coluna derivada com divisor zero. |
| `removido_por_filtro` | filtrado | Não atende ao filtro (o detalhe descreve a condição). |
| `registro_duplicado` | duplicado | Repete a chave de um registro mantido (o detalhe cita qual). |

O `rejected.parquet` guarda as colunas `__df_row`, `__df_line` (linha física no arquivo; nula em transformações), `__df_reason`, `__df_column`, `__df_detail`, `__df_category`, `__df_rule`, `__df_duplicate_of` e os valores de entrada em texto. Versões da Fase 1 têm só as cinco primeiras colunas de metadados; a API lê as colunas do próprio arquivo.

## Estados do job

`queued` (Aguardando) → `validating` (Validando) → `processing` (Processando) → `saving` (Salvando) → `succeeded` (Concluído) | `failed` (Falhou) | `cancelled` (Cancelado).

- **Idempotência**: `Idempotency-Key` na criação (importação e transformação); reivindicação condicional na execução; chaves de armazenamento por job; `UNIQUE(job_id)` em versões; índice único parcial de um job ativo por dataset.
- **Retentativas**: falhas transitórias (S3, banco, rede) devolvem o job para `queued` com aviso e o Celery reagenda com backoff exponencial; após `max_attempts` (3) o job falha com `indisponibilidade`. Falhas permanentes (encoding incompatível, cabeçalho divergente, integridade, planilha recusada, regras inválidas para a versão de origem) falham na hora com mensagem clara.
- **Cancelamento cooperativo**: na fila, cancela atomicamente; em execução, marca `cancel_requested_at` e o worker para no próximo ponto seguro (troca de etapa ou fim de lote). O status só vira `cancelled` depois que a execução parou; objetos parciais são removidos.
- **Recuperação**: jobs em execução sem heartbeat por 5 min voltam para a fila (ou falham ao exceder tentativas); jobs na fila sem publicação há 10 min são republicados. Roda no beat a cada minuto e na inicialização do worker.
- **Progresso**: CSV por bytes lidos; transformação por registros da versão de origem; XLSX só pela contagem de registros (sem percentual, porque a leitura não expõe bytes consumidos).

## Versionamento e linhagem

Cada processamento bem-sucedido cria uma `DatasetVersion` imutável com: arquivo de origem (`upload_id`), job, responsável, data, esquema das colunas (com contagem de nulos), reconciliação, versão das regras, tamanho e SHA-256 do Parquet, e `transformations`:

- importação: `{"kind": "import", "source_format", "parse_options", "steps": []}`;
- transformação: `{"kind": "transform", "source_version_id", "source_version_number", "transformation_set": {"id", "name", "revision"}, "steps": [regras aplicadas]}`, além de `parent_version_id` e `transformation_set_id` como colunas.

Conjuntos de regras (`transformation_sets` + `transformation_rules`) são reutilizáveis e têm revisão: cada alteração incrementa `revision`. O job congela uma cópia das regras na criação, então editar ou excluir o conjunto depois não muda o que um job aplica nem o que uma versão registra. Exemplo de cadeia: v1 (importação) → v2 (trata nulos, a partir da v1) → v3 (remove duplicidades, a partir da v2). O dataset aponta para a versão mais recente; versões anteriores continuam consultáveis (`?version_id=`) e podem servir de origem para outra transformação. Nenhuma versão nem arquivo original é sobrescrito.

## Métricas registradas por job

`timings_ms`: envio do arquivo (importação), leitura e validação, processamento (leitura, conversão ou regras, escrita Parquet, deduplicação), persistência e total; `rows_per_second`; `peak_memory_mb` (via `resource` no Linux; indisponível no Windows).
