# Business Intelligence: consultas analíticas e dashboards

A Fase 4 entrega o Dashboard geral, os dashboards salvos e o Construtor. Todos os números são calculados pela API a partir do Parquet da versão, com DuckDB, no momento em que a tela pede. O banco guarda só a **definição** de cada widget, nunca resultados.

## Consulta analítica

Uma consulta é um JSON de vocabulário fechado, validado por Pydantic (`extra="forbid"`) e conferido contra o esquema da versão antes de virar SQL (`backend/app/analytics/aggregate.py`):

| Campo | O que aceita |
| --- | --- |
| `metrics` | 1 a 6 medidas `{aggregation, column}`. |
| `dimension` | Opcional: `{column, granularity}`. |
| `filters` + `match` | Os mesmos filtros tipados do explorer e das regras de filtro (até 20), combinados por E ou OU. |
| `sort`, `direction`, `limit` | Ordenar pela primeira medida (padrão, decrescente) ou pela dimensão; de 1 a 100 grupos. |
| `comparison` | Opcional: `{column, start, end, mode}` para comparar o período atual com o anterior. |
| `extra_filters` | Até 2 grupos de filtros combinados com E, cada um com o próprio E/OU (filtros gerais de um dashboard e filtros da tela). |

### Agregações por tipo de coluna

| Agregação | Sem coluna | Texto, booleano | Inteiro, decimal | Data, data e hora |
| --- | --- | --- | --- | --- |
| `count` | registros | valores preenchidos | valores preenchidos | valores preenchidos |
| `count_distinct` | — | ✓ | ✓ | ✓ |
| `sum`, `avg` | — | — | ✓ | — |
| `min`, `max` | — | — | ✓ | ✓ |

O resultado informa o **tipo de cada medida**, não o significado: contagens são inteiras; somas, mínimos e máximos têm o tipo e a escala da coluna; a média é decimal com duas casas além da escala da coluna (calculada pelo DuckDB em ponto flutuante e arredondada nessa escala). Decimais trafegam como texto para não perder precisão. Nenhuma coluna numérica é tratada como dinheiro: o Dashboard geral só mostra soma, média, máximo e mínimo depois que o usuário escolhe a medida, e um widget novo começa contando registros.

### Dimensões e grupos

- Servem como dimensão texto, booleano, inteiro (códigos), data e data e hora. **Decimais não**: valores contínuos viram um grupo por valor; para eles existe o filtro de faixa.
- Datas são agrupadas por dia, semana (começando na segunda-feira), mês (padrão), trimestre ou ano; o grupo é o primeiro dia do intervalo.
- Registros sem valor na dimensão formam um grupo próprio ("sem valor"), em vez de sumir.
- Grupos de categoria são cortados em `limit`. Os demais aparecem somados em **"Outros"**, calculados sobre os registros fora dos grupos mostrados (vale também para média, mínimo e contagem distinta). A resposta traz `total_groups`.
- Séries temporais saem em ordem cronológica e **não são cortadas**, porque um corte esconderia parte do período. Acima de 1.000 pontos, a consulta é recusada (`too_many_points`) pedindo uma granularidade maior.

### Comparação entre períodos

O período atual vai de `start` a `end`, com as duas datas incluídas. O anterior pode ser:

- `previous_period`: o período de mesma duração imediatamente antes. Fevereiro de 2025 (28 dias) compara com 04/01 a 31/01.
- `previous_year`: as mesmas datas no ano anterior. 29/02 vira 28/02.

Cada medida é calculada nos dois períodos numa única leitura (`FILTER` do SQL). Em colunas de data e hora vale o dia da data. Sem dados no período anterior, a soma anterior é **nula**, não zero, e a interface mostra a variação como "—". A cor da variação é neutra: subir não é necessariamente bom. A comparação não se aplica a uma dimensão de data.

### Limites

20 filtros por grupo, 6 medidas, 100 grupos e 1.000 pontos por série. Os períodos de comparação vão até 3.660 dias. Toda consulta tem **10 s** de tempo-limite e é interrompida pelo DuckDB ao exceder (`query_timeout`). As consultas rodam na conexão isolada do explorer: sem rede, só o diretório de cache, 2 threads e 512 MB.

## Dashboards persistidos

Tabelas `dashboards` e `dashboard_widgets` (migration `0004`, aditiva):

- Um dashboard tem nome único no workspace, descrição, dataset e versão. Sem versão, **acompanha a versão atual**; com versão, fica **fixado** nela. Uma versão fixada não pode ser excluída enquanto houver dashboard apontando para ela (FK sem `ON DELETE`).
- Os **filtros do dashboard** valem para todos os widgets. Quem abre o dashboard soma a eles os **filtros da tela**: período, valores de uma coluna (categoria, status, responsável…), faixa numérica e filtros avançados.
- Cada widget guarda título, tipo de gráfico, tamanho (¼, ½ ou largura inteira), posição e a consulta (`config`), no máximo 24 por dashboard.
- Tipos: card KPI, linha, área, barras, barras horizontais, pizza, rosca e tabela analítica. Regras por tipo (`check_chart_rules`):
  - um KPI tem uma medida e nenhuma dimensão;
  - os demais exigem dimensão;
  - pizza e rosca usam uma única contagem ou soma, partes de um todo, sobre uma categoria;
  - linha e área não comparam períodos.
- Ao salvar, tudo é validado contra a versão resultante: filtros, colunas, tipos e regras do gráfico. O erro aponta o widget (`invalid_widget`, `details.widget_index`).
- Reorganizar é enviar a lista completa na nova ordem (`PATCH`). Widgets com `id` mantêm a identidade; os sem `id` são novos; os ausentes são removidos.
- Se a versão atual mudar de esquema (uma coluna renomeada, por exemplo), o widget afetado responde `widget_incompatible` explicando a versão e a coluna. Os demais continuam funcionando, e salvar exige corrigir o widget ou fixar uma versão compatível.

## Permissões

| Ação | Permissão | Perfis |
| --- | --- | --- |
| Abrir o Dashboard geral, listar e abrir dashboards, aplicar filtros na tela | `datasets:view` | todos |
| Criar, editar, reorganizar e excluir dashboards | `dashboards:manage` | Analista, Administrador |

Tudo é filtrado pelo workspace da sessão; dashboard, widget, dataset ou versão de outro workspace respondem 404. Criar, editar e excluir ficam na auditoria (`dashboard.created`, `dashboard.updated`, `dashboard.deleted`).

## API

| Método | Rota | Descrição |
| --- | --- | --- |
| POST | `/datasets/{id}/analytics` | Consulta avulsa sobre uma versão (`version_id` opcional) |
| GET | `/dashboards` | Dashboards do workspace |
| POST | `/dashboards` | Cria um dashboard com seus widgets |
| GET | `/dashboards/{id}` | Configuração, versão fixada e versão usada agora |
| PATCH | `/dashboards/{id}` | Altera nome, versão, filtros ou widgets (lista completa, nova ordem) |
| DELETE | `/dashboards/{id}` | Exclui o dashboard (datasets e versões não mudam) |
| POST | `/dashboards/{id}/query` | Calcula um widget (`widget_id`) com os filtros da tela (`extra_filters`) |

Cada widget é calculado numa requisição própria: um widget lento ou incompatível não bloqueia os outros, e cada um mostra seu carregamento e seu erro.
