# Dados de demonstração

Todos os dados são **fictícios**, gerados por `scripts/generate_samples.py` (seed 42). Nomes são combinações aleatórias de listas genéricas e não representam pessoas reais.

| Arquivo | Delimitador | Colunas | Objetivo |
| --- | --- | --- | --- |
| `vendas_1000.csv` | `;` | data_venda (dd/mm/aaaa), vendedor, equipe, produto, categoria, quantidade, valor (1.234,56), status, canal | Fluxo feliz com formato brasileiro. |
| `atendimentos_1000.csv` | `,` | data_atendimento (dd/mm/aaaa hh:mm:ss), operador, equipe, campanha, tipo_atendimento, duracao_segundos, status, resultado | Data e hora, inteiros, outro delimitador. |
| `qualidade_1000.csv` | `;` | mesmas de vendas | Problemas propositais: duplicidades (~4%), espaços excedentes, datas inválidas (`31/02/2025`, `ontem`), valores com formatação inconsistente (`R$ 1.234,56`, `1234.56`), nulos, quantidades não numéricas, registros incompletos, linhas vazias e caixa inconsistente. |

Versões com 10.000 e 100.000 linhas (e qualquer outro tamanho) são geradas em `samples/generated/` (ignorada pelo git):

```bash
python scripts/generate_samples.py                       # 1.000, 10.000 e 100.000 linhas
python scripts/generate_samples.py --rows 1000000 --only vendas --seed 7
```

Mesma seed e mesmo tamanho produzem arquivos idênticos byte a byte.
