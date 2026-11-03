/**
 * Combinações válidas de gráfico, medida e dimensão — o mesmo contrato do backend
 * (`dashboards_service.check_chart_rules` e `analytics/aggregate.py`), usado aqui só para
 * guiar a edição. A API valida tudo de novo antes de salvar ou calcular.
 */

import { isNumeric, isTemporal } from '@/features/transformations/rules'
import type {
  AggregateSpec,
  Aggregation,
  ChartType,
  ColumnSpec,
  DataType,
  WidgetConfig,
} from '@/types/api'

export const MAX_METRICS = 6
export const MAX_WIDGETS = 24
export const PART_OF_WHOLE: Aggregation[] = ['count', 'sum']

/** Agregações aceitas por tipo de coluna; sem coluna, só a contagem de registros. */
export function aggregationsFor(type: DataType | null): Aggregation[] {
  if (type === null) return ['count']
  if (isNumeric(type)) return ['sum', 'avg', 'min', 'max', 'count', 'count_distinct']
  if (isTemporal(type)) return ['min', 'max', 'count', 'count_distinct']
  return ['count', 'count_distinct']
}

/** Colunas que servem de dimensão: categorias, inteiros (códigos) e datas. Decimais não. */
export function dimensionColumns(schema: ColumnSpec[]): ColumnSpec[] {
  return schema.filter((c) => c.data_type !== 'decimal')
}

export const temporalColumns = (schema: ColumnSpec[]) =>
  schema.filter((c) => isTemporal(c.data_type))
export const numericColumns = (schema: ColumnSpec[]) => schema.filter((c) => isNumeric(c.data_type))
export const textColumns = (schema: ColumnSpec[]) => schema.filter((c) => c.data_type === 'text')

export interface ChartRules {
  needsDimension: boolean
  singleMetric: boolean
  partOfWhole: boolean
  categoricalOnly: boolean
  allowComparison: boolean
}

export const CHART_RULES: Record<ChartType, ChartRules> = {
  kpi: {
    needsDimension: false,
    singleMetric: true,
    partOfWhole: false,
    categoricalOnly: false,
    allowComparison: true,
  },
  line: {
    needsDimension: true,
    singleMetric: false,
    partOfWhole: false,
    categoricalOnly: false,
    allowComparison: false,
  },
  area: {
    needsDimension: true,
    singleMetric: false,
    partOfWhole: false,
    categoricalOnly: false,
    allowComparison: false,
  },
  bar: {
    needsDimension: true,
    singleMetric: false,
    partOfWhole: false,
    categoricalOnly: false,
    allowComparison: true,
  },
  bar_horizontal: {
    needsDimension: true,
    singleMetric: false,
    partOfWhole: false,
    categoricalOnly: false,
    allowComparison: true,
  },
  pie: {
    needsDimension: true,
    singleMetric: true,
    partOfWhole: true,
    categoricalOnly: true,
    allowComparison: false,
  },
  donut: {
    needsDimension: true,
    singleMetric: true,
    partOfWhole: true,
    categoricalOnly: true,
    allowComparison: false,
  },
  table: {
    needsDimension: true,
    singleMetric: false,
    partOfWhole: false,
    categoricalOnly: false,
    allowComparison: true,
  },
}

const typeOf = (schema: ColumnSpec[], name: string | null | undefined): DataType | null =>
  schema.find((c) => c.name === name)?.data_type ?? null

/** Primeiro problema da configuração, em português; nulo quando o widget pode ser salvo. */
export function widgetProblem(widget: WidgetConfig, schema: ColumnSpec[]): string | null {
  const rules = CHART_RULES[widget.chart_type]
  const { query } = widget
  if (!widget.title.trim()) return 'Dê um título ao widget.'
  if (query.metrics.length === 0) return 'Escolha ao menos uma medida.'
  if (rules.singleMetric && query.metrics.length !== 1) return 'Este gráfico usa uma única medida.'
  for (const [index, metric] of query.metrics.entries()) {
    const type = metric.column ? typeOf(schema, metric.column) : null
    if (metric.column && type === null) return `Medida ${index + 1}: coluna indisponível.`
    if (!aggregationsFor(type).includes(metric.aggregation))
      return `Medida ${index + 1}: agregação incompatível com a coluna.`
  }
  if (rules.partOfWhole && !PART_OF_WHOLE.includes(query.metrics[0]?.aggregation ?? 'count'))
    return 'Pizza e rosca mostram partes de um todo: use contagem ou soma.'
  if (!rules.needsDimension && query.dimension) return 'Um card KPI não tem dimensão.'
  if (rules.needsDimension) {
    if (!query.dimension) return 'Escolha a dimensão do gráfico.'
    const type = typeOf(schema, query.dimension.column)
    if (type === null) return 'Dimensão: coluna indisponível.'
    if (type === 'decimal') return 'Decimais não servem como dimensão; use um filtro de faixa.'
    if (rules.categoricalOnly && isTemporal(type))
      return 'Pizza e rosca usam uma dimensão de categoria.'
  }
  if (query.comparison) {
    if (!rules.allowComparison) return 'Este gráfico não compara períodos.'
    if (query.dimension && isTemporal(typeOf(schema, query.dimension.column) ?? 'text'))
      return 'A comparação não se aplica a uma dimensão de data.'
    if (!query.comparison.start || !query.comparison.end) return 'Informe o período atual.'
    if (query.comparison.end < query.comparison.start)
      return 'O fim do período não pode ser anterior ao início.'
  }
  return null
}

/** Widget inicial de cada tipo, com colunas compatíveis do esquema quando existirem. */
export function defaultWidget(chartType: ChartType, schema: ColumnSpec[]): WidgetConfig {
  const temporal = temporalColumns(schema)[0]
  const category = textColumns(schema)[0] ?? dimensionColumns(schema)[0]
  // Começa contando registros: a medida numérica é escolha de quem monta o widget, nunca
  // presumida (uma coluna numérica não é necessariamente receita).
  const metric = { aggregation: 'count' as const, column: null }
  let query: AggregateSpec
  switch (chartType) {
    case 'kpi':
      query = { metrics: [metric] }
      break
    case 'line':
    case 'area':
      query = {
        metrics: [metric],
        dimension: temporal
          ? { column: temporal.name, granularity: 'month' }
          : category
            ? { column: category.name }
            : null,
      }
      break
    default:
      query = { metrics: [metric], dimension: category ? { column: category.name } : null }
  }
  return {
    title: '',
    chart_type: chartType,
    size: chartType === 'kpi' ? 'small' : chartType === 'table' ? 'large' : 'medium',
    query: { limit: 10, ...query },
  }
}

/** Ajusta a consulta quando o tipo de gráfico muda, mantendo o que ainda faz sentido. */
export function adaptToChart(
  widget: WidgetConfig,
  chartType: ChartType,
  schema: ColumnSpec[],
): WidgetConfig {
  const rules = CHART_RULES[chartType]
  const fallback = defaultWidget(chartType, schema).query
  let metrics = rules.singleMetric ? widget.query.metrics.slice(0, 1) : widget.query.metrics
  if (rules.partOfWhole)
    metrics = metrics.map((m) =>
      PART_OF_WHOLE.includes(m.aggregation) ? m : { ...m, aggregation: m.column ? 'sum' : 'count' },
    )
  let dimension = rules.needsDimension ? (widget.query.dimension ?? fallback.dimension) : null
  if (dimension && rules.categoricalOnly) {
    const type = schema.find((c) => c.name === dimension?.column)?.data_type
    if (type && isTemporal(type)) dimension = fallback.dimension ?? null
  }
  return {
    ...widget,
    chart_type: chartType,
    query: {
      ...widget.query,
      metrics,
      dimension,
      comparison: rules.allowComparison ? widget.query.comparison : null,
    },
  }
}
