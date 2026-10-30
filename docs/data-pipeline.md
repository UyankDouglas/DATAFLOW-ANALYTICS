# Pipeline de dados

Regras de conversão versionadas em `RULES_VERSION = 1.0.0` (`backend/app/processing/types.py`). Cada versão de dataset registra a versão das regras com que foi produzida.

## Etapas

| Etapa | Onde | O que acontece |
| --- | --- | --- |
| **Upload** | API (`services/upload_service.py`) | Corpo em streaming → disco temporário; extensão permitida (`.csv`); limite por formato (100 MB CSV, configurável); assinatura binária (ZIP/XLSX, XLS, PDF, executáveis, imagens, GZIP, RAR, 7z) e UTF-16 recusados; bytes nulos recusados; validação UTF-8 incremental; SHA-256; contagem de quebras de linha; detecção de delimitador e separadores numéricos. Envio ao S3 com chave aleatória. |
| **Validação** | API | Arquivo vazio, binário ou com conteúdo incompatível com a extensão é recusado com código de erro e auditoria (sem conteúdo). |
| **Pré-visualização** | API (`services/preview_service.py`) | Lê só os primeiros 2 MB (Range GET). Mostra 20 linhas, infere tipos sobre até 1.000 registros e calcula nulos, distintos, linhas vazias e registros com campos a mais/menos **da amostra**. |
| **Mapeamento** | API (`services/import_service.py`) | Valida nome único (sem diferenciar maiúsculas), prefixo reservado `__df_`, formatos permitidos, escala decimal, correspondência com o cabeçalho atual, encoding confirmado e confirmação explícita de datas ambíguas. Salva o mapeamento no dataset (reutilizável). |
| **Processamento assíncrono** | Worker (`services/job_runner.py`) | Reivindica o job, baixa o original, confere SHA-256 e executa o pipeline em lotes. |
| **Limpeza/normalização** (Fase 1) | `processing/convert.py` | Somente normalização de esquema: nulos configurados, trim em campos não-texto antes da conversão, separadores numéricos. Texto é preservado exatamente. Transformações configuráveis chegam na Fase 2. |
| **Deduplicação** | — | Fase 2. Registrada explicitamente como `duplicates: null`, `duplicates_policy: "nao_aplicada"`. |
| **Armazenamento versionado** | Worker | `data.parquet` (válidos, tipados) e `rejected.parquet` (rejeitados, valores originais em texto + motivo). Publicação em uma única transação. |

## Tipos e regras de conversão

| Tipo | Polars / Parquet | Regra |
| --- | --- | --- |
| Texto | `String` / `string` | Preservado como recebido (sem trim). |
| Inteiro | `Int64` / `int64` | Após remover separador de milhar: `^[+-]?\d+$`; overflow de 64 bits rejeita. |
| Decimal | `Decimal(38, s)` / `decimal128(38, s)` | Separadores configurados; `^[+-]?(\d+(\.\d*)?|\.\d+)$`; mais de `s` casas → rejeição (sem arredondar). |
| Data | `Date` / `date32` | Formato explícito da allowlist (`dd/mm/aaaa`, `aaaa-mm-dd`, …). |
| Data e hora | `Datetime(us)` / `timestamp[us]` | Formato explícito; sem fuso (valor como registrado). |
| Booleano | `Boolean` / `bool` | `true/verdadeiro/sim/s/yes/y/1` e `false/falso/não/nao/n/no/0`, sem diferenciar maiúsculas. |

**Inferência** (amostra): booleano → inteiro → decimal → data → data e hora → texto. Valores numéricos com zeros à esquerda (CEP, matrícula, SKU) ficam como **texto** e geram aviso. Datas que servem a mais de um formato (ex.: `01/02/2024`) são marcadas como **ambíguas** e exigem confirmação antes do processamento. Valores nulos padrão: `""`, `NULL`, `null` (configurável).

## Reconciliação

```
recebidos = válidos + rejeitados
```

- **Recebidos**: todos os registros após o cabeçalho, inclusive linhas vazias e malformadas.
- **Válidos**: publicados na versão (`data.parquet`).
- **Rejeitados**: cada registro conta **uma vez**, pelo primeiro motivo encontrado (estrutura antes de tipo; colunas na ordem do arquivo). A coluna e o valor original ficam no `rejected.parquet`.
- **Duplicados**: não avaliados na Fase 1 (campo `null` + política explícita). Quando a deduplicação existir, a política definirá se duplicados saem dos válidos — sem contagem dupla.

Se a igualdade não fechar, o job falha com `reconciliacao` e nada é publicado.

### Códigos de rejeição

| Código | Significado |
| --- | --- |
| `linha_vazia` | Registro sem nenhum valor preenchido. |
| `campos_a_menos` / `campos_a_mais` | Quantidade de campos diferente do cabeçalho (o detalhe informa quantos). |
| `csv_malformado` | Aspas malformadas ou campo acima do limite (1 MB). |
| `tipo_invalido` | Valor não converte para o tipo configurado (detalhe cita tipo e formato). |
| `casas_decimais_excedidas` | Mais casas decimais que a escala configurada. |

## Estados do job

`queued` (Aguardando) → `validating` (Validando) → `processing` (Processando) → `saving` (Salvando) → `succeeded` (Concluído) | `failed` (Falhou) | `cancelled` (Cancelado).

- **Idempotência**: `Idempotency-Key` na criação; reivindicação condicional na execução; chaves de armazenamento por job; `UNIQUE(job_id)` em versões; índice único parcial de um job ativo por dataset.
- **Retentativas**: falhas transitórias (S3, banco, rede) devolvem o job para `queued` com aviso e o Celery reagenda com backoff exponencial; após `max_attempts` (3) o job falha com `indisponibilidade`. Falhas permanentes (encoding incompatível, cabeçalho divergente, integridade) falham na hora com mensagem clara.
- **Cancelamento cooperativo**: na fila, cancela atomicamente; em execução, marca `cancel_requested_at` e o worker para no próximo ponto seguro (troca de etapa ou fim de lote). O status só vira `cancelled` depois que a execução parou; objetos parciais são removidos.
- **Recuperação**: jobs em execução sem heartbeat por 5 min voltam para a fila (ou falham ao exceder tentativas); jobs na fila sem publicação há 10 min são republicados. Roda no beat a cada minuto e na inicialização do worker.

## Versionamento

Cada processamento bem-sucedido cria uma `DatasetVersion` imutável com: arquivo de origem (`upload_id`), job, responsável, data, esquema das colunas (com contagem de nulos), configuração de leitura e passos de transformação, reconciliação, versão das regras, tamanho e SHA-256 do Parquet. O dataset aponta para a versão atual; versões anteriores continuam consultáveis (`?version_id=`). Reprocessar nunca sobrescreve uma versão nem o arquivo original.

## Métricas registradas por job

`timings_ms`: envio do arquivo, leitura e validação, processamento (leitura/tokenização, conversão, escrita Parquet), persistência e total; `rows_per_second`; `peak_memory_mb` (via `resource` no Linux; indisponível no Windows).
