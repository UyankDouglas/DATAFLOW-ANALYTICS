import { DATA_TYPE_LABEL, DATE_FORMATS, DATETIME_FORMATS } from '@/features/datasets/column-form'
import type { Tone } from '@/features/jobs/status'
import type {
  ColumnSpec,
  Condition,
  DataType,
  ExclusionCategory,
  Expression,
  FilterOperator,
  Rule,
  RuleOperation,
} from '@/types/api'

/** Operações da lista fechada do backend, na ordem em que aparecem no seletor. */
export const OPERATION_LABEL: Record<RuleOperation, string> = {
  trim: 'Remover espaços excedentes',
  normalize_text: 'Normalizar texto',
  change_case: 'Padronizar maiúsculas/minúsculas',
  convert_type: 'Converter tipo',
  standardize_dates: 'Padronizar datas',
  fix_numbers: 'Corrigir formatos numéricos',
  handle_nulls: 'Tratar valores nulos',
  remove_empty_rows: 'Remover linhas totalmente vazias',
  filter_rows: 'Filtrar registros',
  rename_columns: 'Renomear colunas',
  derived_column: 'Criar coluna derivada',
  deduplicate: 'Remover duplicidades',
}

export const OPERATION_HINT: Record<RuleOperation, string> = {
  trim: 'Tira espaços do início e do fim e, opcionalmente, repetidos no meio.',
  normalize_text: 'Unifica caracteres equivalentes (Unicode) e pode remover acentos.',
  change_case: 'Converte o texto para maiúsculas, minúsculas ou iniciais maiúsculas.',
  convert_type: 'Muda o tipo da coluna; valores que não convertem rejeitam o registro.',
  standardize_dates: 'Lê datas escritas em vários formatos e grava um tipo data único.',
  fix_numbers: 'Interpreta números com moeda, milhar e decimal locais (ex.: R$ 1.234,56).',
  handle_nulls: 'Preenche nulos com um valor fixo ou rejeita registros com nulo.',
  remove_empty_rows: 'Descarta registros em que todas as colunas estão vazias.',
  filter_rows: 'Mantém apenas registros que atendem às condições; os demais ficam registrados.',
  rename_columns: 'Dá novos nomes às colunas da versão.',
  derived_column: 'Calcula uma nova coluna a partir de outras, sem fórmulas livres.',
  deduplicate: 'Mantém o primeiro (ou último) registro de cada chave. Sempre a última regra.',
}

export const OPERATOR_LABEL: Record<FilterOperator, string> = {
  eq: 'igual a',
  ne: 'diferente de',
  gt: 'maior que',
  gte: 'maior ou igual a',
  lt: 'menor que',
  lte: 'menor ou igual a',
  between: 'entre',
  contains: 'contém',
  not_contains: 'não contém',
  starts_with: 'começa com',
  ends_with: 'termina com',
  in: 'está em',
  not_in: 'não está em',
  is_null: 'é nulo',
  not_null: 'não é nulo',
  is_true: 'é verdadeiro',
  is_false: 'é falso',
}

const COMPARABLE: FilterOperator[] = [
  'eq',
  'ne',
  'gt',
  'gte',
  'lt',
  'lte',
  'between',
  'in',
  'not_in',
  'is_null',
  'not_null',
]

export const OPERATORS_BY_TYPE: Record<DataType, FilterOperator[]> = {
  text: [
    'eq',
    'ne',
    'contains',
    'not_contains',
    'starts_with',
    'ends_with',
    'in',
    'not_in',
    'is_null',
    'not_null',
  ],
  boolean: ['is_true', 'is_false', 'is_null', 'not_null'],
  integer: COMPARABLE,
  decimal: COMPARABLE,
  date: COMPARABLE,
  datetime: COMPARABLE,
}

export const NO_VALUE_OPERATORS: FilterOperator[] = ['is_null', 'not_null', 'is_true', 'is_false']
export const LIST_OPERATORS: FilterOperator[] = ['in', 'not_in']

export const DATE_PART_LABEL = {
  year: 'Ano',
  month: 'Mês',
  day: 'Dia',
  quarter: 'Trimestre',
  weekday: 'Dia da semana (1 = segunda)',
  year_month: 'Ano-mês (aaaa-mm)',
} as const

export const ARITHMETIC_LABEL = {
  add: 'somar (+)',
  subtract: 'subtrair (−)',
  multiply: 'multiplicar (×)',
  divide: 'dividir (÷)',
} as const

export const REASON_LABEL: Record<string, string> = {
  tipo_invalido: 'Tipo inválido',
  casas_decimais_excedidas: 'Casas decimais excedidas',
  valor_nulo: 'Valor nulo',
  linha_vazia: 'Linha vazia',
  removido_por_filtro: 'Removido pelo filtro',
  divisao_por_zero: 'Divisão por zero',
  registro_duplicado: 'Registro duplicado',
}

export const CATEGORY_LABEL: Record<ExclusionCategory, string> = {
  rejeitado: 'Rejeitado',
  filtrado: 'Filtrado',
  duplicado: 'Duplicado',
}

export const CATEGORY_TONE: Record<ExclusionCategory, Tone> = {
  rejeitado: 'warning',
  filtrado: 'info',
  duplicado: 'neutral',
}

export const isTemporal = (type: DataType) => type === 'date' || type === 'datetime'
export const isNumeric = (type: DataType) => type === 'integer' || type === 'decimal'

function derivedType(expression: Expression): Pick<ColumnSpec, 'data_type' | 'scale'> {
  switch (expression.kind) {
    case 'arithmetic':
      return { data_type: 'decimal', scale: expression.scale }
    case 'concat':
      return { data_type: 'text', scale: null }
    case 'date_part':
      return { data_type: expression.part === 'year_month' ? 'text' : 'integer', scale: null }
    case 'date_diff_days':
      return { data_type: 'integer', scale: null }
  }
}

function replace(schema: ColumnSpec[], name: string, next: ColumnSpec): ColumnSpec[] {
  return schema.map((column) => (column.name === name ? next : column))
}

/** Efeito de uma regra no esquema (espelho do planejamento do servidor, sem validação). */
function applyToSchema(rule: Rule, schema: ColumnSpec[]): ColumnSpec[] {
  switch (rule.operation) {
    case 'convert_type': {
      const source = schema.find((column) => column.name === rule.column)
      if (!source) return schema
      const fromText = source.data_type === 'text'
      return replace(schema, source.name, {
        name: source.name,
        data_type: rule.target,
        format:
          isTemporal(rule.target) && fromText
            ? (rule.format ?? null)
            : rule.target === source.data_type
              ? (source.format ?? null)
              : null,
        scale: rule.target === 'decimal' ? (rule.scale ?? null) : null,
      })
    }
    case 'standardize_dates':
      return replace(schema, rule.column, { name: rule.column, data_type: rule.target })
    case 'fix_numbers':
      return replace(schema, rule.column, {
        name: rule.column,
        data_type: rule.target,
        scale: rule.target === 'decimal' ? (rule.scale ?? null) : null,
      })
    case 'rename_columns':
      return schema.map((column) => {
        const target = rule.mapping[column.name]?.trim()
        return target ? { ...column, name: target } : column
      })
    case 'derived_column':
      return [...schema, { name: rule.name, ...derivedType(rule.expression) }]
    default:
      return schema
  }
}

export interface SchemaSimulation {
  /** Esquema visto por cada regra (antes de aplicá-la). */
  before: ColumnSpec[][]
  output: ColumnSpec[]
}

export function simulateSchema(rules: Rule[], input: ColumnSpec[]): SchemaSimulation {
  let schema = input
  const before: ColumnSpec[][] = []
  for (const rule of rules) {
    before.push(schema)
    if (rule.enabled) schema = applyToSchema(rule, schema)
  }
  return { before, output: schema }
}

const namesOf = (schema: ColumnSpec[], predicate: (type: DataType) => boolean = () => true) =>
  schema.filter((column) => predicate(column.data_type)).map((column) => column.name)

/** Regra nova com valores iniciais sensatos para o esquema atual. */
export function defaultRule(operation: RuleOperation, schema: ColumnSpec[]): Rule {
  const text = namesOf(schema, (type) => type === 'text')
  const first = schema[0]?.name ?? ''
  const firstText = text[0] ?? first
  switch (operation) {
    case 'trim':
      return { operation, enabled: true, columns: text, collapse_internal: true }
    case 'normalize_text':
      return { operation, enabled: true, columns: text, remove_accents: true, form: 'NFKC' }
    case 'change_case':
      return { operation, enabled: true, columns: firstText ? [firstText] : [], mode: 'title' }
    case 'convert_type':
      return { operation, enabled: true, column: first, target: 'text' }
    case 'standardize_dates':
      return {
        operation,
        enabled: true,
        column: firstText,
        target: 'date',
        formats: ['%d/%m/%Y', '%Y-%m-%d'],
      }
    case 'fix_numbers':
      return {
        operation,
        enabled: true,
        column: firstText,
        target: 'decimal',
        scale: 2,
        decimal_separator: ',',
        thousands_separator: '.',
        strip_currency: true,
        parentheses_negative: false,
      }
    case 'handle_nulls':
      return { operation, enabled: true, columns: first ? [first] : [], strategy: 'reject' }
    case 'remove_empty_rows':
      return { operation, enabled: true }
    case 'filter_rows':
      return {
        operation,
        enabled: true,
        match: 'all',
        conditions: [{ column: first, operator: 'not_null' }],
      }
    case 'rename_columns':
      return { operation, enabled: true, mapping: {} }
    case 'derived_column': {
      const numeric = namesOf(schema, isNumeric)
      const expression: Expression =
        numeric.length > 0
          ? {
              kind: 'arithmetic',
              operator: 'multiply',
              left: { column: numeric[0] },
              right: numeric[1] ? { column: numeric[1] } : { value: '1' },
              scale: 2,
            }
          : {
              kind: 'concat',
              parts: [{ column: first }, { column: schema[1]?.name ?? first }],
              separator: ' ',
            }
      return { operation, enabled: true, name: 'nova_coluna', expression }
    }
    case 'deduplicate':
      return { operation, enabled: true, columns: [], keep: 'first' }
  }
}

/** Insere a regra no fim, mas antes de uma deduplicação final (que precisa ser a última). */
export function insertRule(rules: Rule[], rule: Rule): Rule[] {
  const last = rules.at(-1)
  if (rule.operation !== 'deduplicate' && last?.operation === 'deduplicate') {
    return [...rules.slice(0, -1), rule, last]
  }
  return [...rules, rule]
}

export function moveRule(rules: Rule[], index: number, delta: -1 | 1): Rule[] {
  const target = index + delta
  if (target < 0 || target >= rules.length) return rules
  const next = [...rules]
  const [moved] = next.splice(index, 1)
  if (moved) next.splice(target, 0, moved)
  return next
}

const list = (names: string[]) => (names.length ? names.join(', ') : 'nenhuma coluna')

function describeCondition(condition: Condition): string {
  const operator = OPERATOR_LABEL[condition.operator]
  if (NO_VALUE_OPERATORS.includes(condition.operator)) return `${condition.column} ${operator}`
  if (LIST_OPERATORS.includes(condition.operator)) {
    return `${condition.column} ${operator} (${(condition.values ?? []).join(', ')})`
  }
  if (condition.operator === 'between') {
    return `${condition.column} entre ${condition.value ?? '?'} e ${condition.value_to ?? '?'}`
  }
  return `${condition.column} ${operator} "${condition.value ?? ''}"`
}

/** Resumo legível de uma regra (lista de regras, histórico e linhagem da versão). */
export function describeRule(rule: Rule): string {
  switch (rule.operation) {
    case 'trim':
    case 'normalize_text':
      return list(rule.columns)
    case 'change_case':
      return `${list(rule.columns)} → ${{ upper: 'MAIÚSCULAS', lower: 'minúsculas', title: 'Iniciais Maiúsculas' }[rule.mode]}`
    case 'convert_type':
      return `${rule.column} → ${DATA_TYPE_LABEL[rule.target]}`
    case 'standardize_dates':
      return `${rule.column}: ${rule.formats.map((f) => DATE_FORMATS[f] ?? DATETIME_FORMATS[f] ?? f).join(' | ')}`
    case 'fix_numbers':
      return `${rule.column} → ${DATA_TYPE_LABEL[rule.target]}`
    case 'handle_nulls':
      return rule.strategy === 'fill'
        ? `${list(rule.columns)}: preencher com "${rule.fill_value ?? ''}"`
        : `${list(rule.columns)}: rejeitar registro`
    case 'remove_empty_rows':
      return 'registros sem nenhum valor'
    case 'filter_rows':
      return rule.conditions.map(describeCondition).join(rule.match === 'all' ? ' e ' : ' ou ')
    case 'rename_columns':
      return (
        Object.entries(rule.mapping)
          .map(([from, to]) => `${from} → ${to}`)
          .join(', ') || 'nenhuma coluna'
      )
    case 'derived_column':
      return `${rule.name} = ${describeExpression(rule.expression)}`
    case 'deduplicate':
      return `chave: ${rule.columns.length ? rule.columns.join(', ') : 'todas as colunas'} · manter ${rule.keep === 'first' ? 'o primeiro' : 'o último'}`
  }
}

function operandText(operand: { column?: string | null; value?: string | null }): string {
  return operand.column ?? `"${operand.value ?? ''}"`
}

function describeExpression(expression: Expression): string {
  switch (expression.kind) {
    case 'arithmetic': {
      const symbol = { add: '+', subtract: '−', multiply: '×', divide: '÷' }[expression.operator]
      return `${operandText(expression.left)} ${symbol} ${operandText(expression.right)}`
    }
    case 'concat':
      return expression.parts.map(operandText).join(' & ')
    case 'date_part':
      return `${DATE_PART_LABEL[expression.part].toLowerCase()} de ${expression.column}`
    case 'date_diff_days':
      return `dias entre ${expression.start} e ${expression.end}`
  }
}
