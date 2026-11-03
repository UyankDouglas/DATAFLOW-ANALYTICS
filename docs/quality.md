# Qualidade dos dados

Cada versão publicada tem um **relatório de qualidade** com indicadores, perfil das colunas, exclusões agrupadas e uma **nota de 0 a 100**. Tudo é calculado sobre os dados reais da versão — o Parquet de válidos (`data.parquet`) e o de exclusões (`rejected.parquet`) — com DuckDB. Implementação em `backend/app/analytics/quality.py`; fórmula versionada em `FORMULA_VERSION = "1.0"`.

## Quando é calculado

- **Ao publicar uma versão** (importação ou transformação): o worker calcula o relatório logo depois da publicação, a partir dos arquivos locais do job. Uma falha nesse cálculo não desfaz a versão; o job registra um aviso.
- **Sob demanda**: versões publicadas antes da Fase 3, ou cujo cálculo falhou, mostram "relatório não calculado". Quem tem `datasets:process` (Analista, Administrador) calcula pela tela ou por `POST /datasets/{id}/versions/{vid}/quality`. Recalcular substitui o relatório da versão; nunca há dois.

Como versões são imutáveis, o relatório de uma versão só muda se a fórmula mudar — e então `formula_version` registra com qual fórmula cada relatório foi feito.

## A nota

```
nota = 100 × (0,4 × validade + 0,4 × completude + 0,2 × unicidade)
```

arredondada a uma casa decimal. Os três componentes vão de 0 a 1:

| Componente | Fórmula | O que mede |
| --- | --- | --- |
| **Validade** | válidos ÷ (válidos + rejeitados) | Dos registros que chegaram a ser avaliados para publicação, quantos passaram. Filtrados (escolha do usuário) e duplicados removidos não entram no denominador. |
| **Completude** | células com valor ÷ (válidos × colunas) | Das células publicadas, quantas têm valor. |
| **Unicidade** | 1 − duplicados restantes ÷ válidos | Dos registros publicados, quantos não repetem outro registro em **todas** as colunas. Nulos contam como iguais entre si. |

**Por que esses pesos.** Validade e completude descrevem se o dado existe e é utilizável, então pesam o mesmo e juntos respondem por 80%. Duplicidade restante distorce contagens e somas, mas não torna o dado inválido: pesa 20%. Mudar os pesos exige incrementar `FORMULA_VERSION`.

**Casos-limite**

| Situação | Nota |
| --- | --- |
| Nenhum registro publicável (válidos + rejeitados = 0), por exemplo tudo filtrado | nula — não há o que avaliar |
| Nenhum válido, algum rejeitado | 0 |
| Algum válido | fórmula completa |

Filtros não penalizam a nota: remover registros fora do escopo é uma decisão de análise, não um defeito do dado. Duplicados **removidos** também não penalizam — já foram tratados —, mas aparecem nos indicadores.

**Exemplo reproduzível** (teste `test_report_counts_validity_completeness_uniqueness_and_issues`): 7 recebidos, 4 válidos, 1 rejeitado, 1 filtrado, 1 duplicado removido; nos 4 válidos, 2 células nulas em 8 e um par de registros idênticos.

```
validade   = 4 ÷ (4 + 1)  = 0,80
completude = 6 ÷ 8        = 0,75
unicidade  = 1 − 1 ÷ 4    = 0,75
nota       = 100 × (0,4 × 0,80 + 0,4 × 0,75 + 0,2 × 0,75) = 77,0
```

Com os dados de demonstração (`qualidade_1000.csv` importado com `data_venda` como data, `quantidade` como inteiro e `valor` como decimal): 938 válidos e 62 rejeitados (validade 0,938), 36 células nulas em 8.442 (completude 0,9957) e 46 duplicados restantes (unicidade 0,9510) — nota **96,4**.

## Indicadores

| Indicador | Definição |
| --- | --- |
| Total de registros | `recebidos` da reconciliação da versão. |
| Registros válidos / rejeitados / filtrados | Categorias da reconciliação (ver `docs/data-pipeline.md`). |
| Registros duplicados | Removidos pela deduplicação (nulo se não aplicada) + restantes na versão (iguais em todas as colunas). |
| Valores nulos | Células nulas entre as publicadas. |
| Percentual de completude | O componente de completude. |
| Colunas com inconsistências | Colunas às quais ao menos uma exclusão foi atribuída (tipo inválido, obrigatória vazia, valor nulo rejeitado, divisão por zero…). Nulos são medidos à parte. |
| Regras violadas | Grupos distintos de exclusão por motivo, coluna e regra, sem contar filtros. Tipo inválido em `valor` e em `quantidade` são duas regras do mapeamento. |
| Violações | Registros excluídos por essas regras. |

## O que é guardado

`quality_reports` guarda nota, componentes, indicadores, perfil das colunas (completude, nulos, distintos, mínimo e máximo de colunas numéricas e de data, exclusões atribuídas), distribuição de nulos por registro e a duração do cálculo. `quality_issues` guarda um grupo por categoria, motivo, coluna e regra, com a contagem e um registro de exemplo.

**Nenhum valor de texto dos dados vai para o PostgreSQL.** A frequência de valores, o valor original de cada inconsistência e o registro completo são lidos do Parquet sob demanda, depois da checagem de workspace.

## Na interface

A tela **Qualidade dos Dados** (`/qualidade`) mostra, por versão:

- a nota com os componentes e os pesos;
- os indicadores;
- completude por coluna e distribuição de nulos;
- erros por categoria e frequência de valores;
- perfil das colunas e duplicidades por chave (análise da versão inteira, sem alterar dados);
- a **tabela de inconsistências** — registro, linha, coluna, valor original, tipo do problema, regra violada e tratamento aplicado — filtrável por categoria, motivo e coluna e paginada no servidor;
- a **comparação entre versões** (nota e componentes de cada uma).

## Custo

Medido em `docs/benchmark.md`: relatório de 100 mil registros em 0,19 a 0,28 s.
