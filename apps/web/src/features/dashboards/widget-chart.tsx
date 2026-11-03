import { ArrowDownRight, ArrowRight, ArrowUpRight } from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatInteger } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { AggregateResult, ChartType } from '@/types/api'

import { COLORS, chartData, type Series } from './chart-data'
import {
  formatAxis,
  formatKey,
  formatMetricValue,
  formatPeriod,
  formatVariation,
  variation,
} from './format'

const OTHERS_COLOR = 'var(--muted-foreground)'
const AXIS = { fill: 'var(--muted-foreground)', fontSize: 12 }
const TOOLTIP = {
  background: 'var(--popover)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  color: 'var(--popover-foreground)',
}

function tooltipFormatter(series: Series[]) {
  return (_value: unknown, _name: unknown, item: { dataKey?: unknown; payload?: unknown }) => {
    const key = String(item.dataKey ?? '')
    const meta = series.find((s) => s.key === key)
    const raw = (item.payload as Record<string, unknown> | undefined)?.[`raw_${key}`]
    return [meta ? formatMetricValue(raw, meta.metric) : String(raw ?? '—'), meta?.label ?? key]
  }
}

export function WidgetChart({
  chartType,
  result,
  title,
}: {
  chartType: ChartType
  result: AggregateResult
  title: string
}) {
  if (chartType === 'kpi') return <KpiView result={result} />
  if (result.rows.length === 0) {
    return (
      <p className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        Nenhum registro atende aos filtros.
      </p>
    )
  }
  if (chartType === 'table') return <AnalyticTable result={result} title={title} />
  return (
    <figure aria-label={title} className="space-y-2">
      {chartType === 'pie' || chartType === 'donut' ? (
        <PieView result={result} donut={chartType === 'donut'} />
      ) : (
        <CartesianView result={result} chartType={chartType} />
      )}
      <ScreenReaderTable result={result} title={title} />
    </figure>
  )
}

function CartesianView({
  result,
  chartType,
}: {
  result: AggregateResult
  chartType: Exclude<ChartType, 'kpi' | 'table' | 'pie' | 'donut'>
}) {
  const temporal = Boolean(result.dimension?.granularity)
  const { points, series } = chartData(result, !temporal)
  const formatter = tooltipFormatter(series)
  const legend = series.length > 1
  const common = {
    data: points,
    margin: { top: 8, right: 12, bottom: 0, left: 0 },
    accessibilityLayer: true,
  }
  const grid = <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
  const tooltip = (
    <Tooltip
      contentStyle={TOOLTIP}
      cursor={{ fill: 'var(--accent)', opacity: 0.4 }}
      formatter={formatter}
    />
  )
  const valueAxis = (
    <YAxis
      tick={AXIS}
      tickLine={false}
      axisLine={false}
      width={56}
      tickFormatter={(value: number) => formatAxis(value)}
    />
  )
  const categoryAxis = (
    <XAxis
      dataKey="label"
      tick={AXIS}
      tickLine={false}
      axisLine={false}
      interval="preserveStartEnd"
      minTickGap={12}
    />
  )
  if (chartType === 'bar_horizontal') {
    return (
      <ResponsiveContainer width="100%" height={Math.max(180, points.length * 34 + 40)}>
        <BarChart {...common} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
          <XAxis
            type="number"
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value: number) => formatAxis(value)}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={128}
            tick={AXIS}
            tickLine={false}
            axisLine={false}
          />
          {tooltip}
          {legend && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={s.color}
              fillOpacity={s.previous ? 0.4 : 1}
              radius={[0, 4, 4, 0]}
            >
              {points.map((p) => (
                <Cell key={p.label} fill={p.others ? OTHERS_COLOR : s.color} />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    )
  }
  if (chartType === 'bar') {
    return (
      <ResponsiveContainer width="100%" height={260}>
        <BarChart {...common}>
          {grid}
          {categoryAxis}
          {valueAxis}
          {tooltip}
          {legend && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={s.color}
              fillOpacity={s.previous ? 0.4 : 1}
              radius={[4, 4, 0, 0]}
            >
              {points.map((p) => (
                <Cell key={p.label} fill={p.others ? OTHERS_COLOR : s.color} />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    )
  }
  if (chartType === 'area') {
    return (
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart {...common}>
          {grid}
          {categoryAxis}
          {valueAxis}
          {tooltip}
          {legend && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s) => (
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              fill={s.color}
              fillOpacity={0.15}
              strokeWidth={2}
              connectNulls
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart {...common}>
        {grid}
        {categoryAxis}
        {valueAxis}
        {tooltip}
        {legend && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            strokeWidth={2}
            dot={points.length <= 24}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

function PieView({ result, donut }: { result: AggregateResult; donut: boolean }) {
  const { points, series } = chartData(result, true)
  const metric = result.metrics[0]
  const total = points.reduce((sum, p) => sum + ((p.s0 as number | null) ?? 0), 0)
  return (
    <div className="grid items-center gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <ResponsiveContainer width="100%" height={220}>
        <PieChart accessibilityLayer>
          <Tooltip contentStyle={TOOLTIP} formatter={tooltipFormatter(series)} />
          <Pie
            data={points}
            dataKey="s0"
            nameKey="label"
            innerRadius={donut ? '55%' : 0}
            outerRadius="90%"
            paddingAngle={donut ? 2 : 0}
            stroke="var(--background)"
          >
            {points.map((p, index) => (
              <Cell
                key={p.label}
                fill={p.others ? OTHERS_COLOR : (COLORS[index % COLORS.length] ?? '')}
              />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <ul className="space-y-1.5 text-sm">
        {points.map((p, index) => (
          <li key={p.label} className="flex items-center gap-2">
            <span
              className="size-2.5 shrink-0 rounded-sm"
              style={{
                background: p.others ? OTHERS_COLOR : COLORS[index % COLORS.length],
              }}
              aria-hidden
            />
            <span className="min-w-0 flex-1 truncate">{p.label}</span>
            <span className="tabular text-muted-foreground">
              {total > 0 ? formatShare(((p.s0 as number | null) ?? 0) / total) : '—'}
            </span>
            <span className="tabular w-24 text-right">
              {metric ? formatMetricValue(p.raw_s0, metric) : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const share = new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 1 })
function formatShare(ratio: number): string {
  return share.format(ratio)
}

function KpiView({ result }: { result: AggregateResult }) {
  const metric = result.metrics[0]
  const row = result.rows[0]
  if (!metric || !row) return null
  const current = row.values[0]
  const previous = row.previous?.[0]
  const ratio = result.comparison ? variation(current, previous) : null
  const Arrow =
    ratio === null || ratio === 0 ? ArrowRight : ratio > 0 ? ArrowUpRight : ArrowDownRight
  return (
    <div className="space-y-1.5">
      <p
        className="tabular text-3xl font-semibold tracking-tight break-all"
        data-testid="kpi-value"
      >
        {formatMetricValue(current, metric)}
      </p>
      <p className="text-xs text-muted-foreground">
        {metric.label}
        {/* Contar registros já é o próprio número: não repete a contagem. */}
        {metric.aggregation === 'count' && !metric.column
          ? null
          : ` · ${formatInteger(result.matched_rows)} registros`}
      </p>
      {result.comparison && (
        <div className="space-y-0.5 pt-1 text-sm">
          <p className="flex items-center gap-1 font-medium">
            {/* Subir não é necessariamente bom: a cor fica neutra e a seta mostra a direção. */}
            <Arrow className="size-4" aria-hidden />
            <span data-testid="kpi-variation">{formatVariation(ratio)}</span>
            <span className="font-normal text-muted-foreground">
              vs. {formatMetricValue(previous, metric)}
            </span>
          </p>
          <p className="text-xs text-muted-foreground">
            {formatPeriod(result.comparison.current_start, result.comparison.current_end)} vs.{' '}
            {formatPeriod(result.comparison.previous_start, result.comparison.previous_end)}
          </p>
        </div>
      )}
    </div>
  )
}

function AnalyticTable({ result, title }: { result: AggregateResult; title: string }) {
  const comparison = Boolean(result.comparison)
  const rows = [
    ...result.rows.map((r) => ({
      label: formatKey(r.key, result.dimension),
      values: r.values,
      previous: r.previous,
      others: false,
    })),
    ...(result.others
      ? [
          {
            label: `Outros (${formatInteger(result.others.groups)} grupos)`,
            values: result.others.values,
            previous: result.others.previous,
            others: true,
          },
        ]
      : []),
  ]
  return (
    <div className="overflow-x-auto">
      <Table>
        <caption className="sr-only">{title}</caption>
        <TableHeader>
          <TableRow>
            <TableHead>{result.dimension?.column ?? ''}</TableHead>
            {result.metrics.map((m) => (
              <TableHead key={m.key} className="text-right">
                {m.label}
              </TableHead>
            ))}
            {comparison &&
              result.metrics.map((m) => (
                <TableHead key={`${m.key}-p`} className="text-right">
                  Anterior · variação
                </TableHead>
              ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.label} className={cn(row.others && 'text-muted-foreground italic')}>
              <TableCell className="max-w-56 truncate font-medium">{row.label}</TableCell>
              {result.metrics.map((m, index) => (
                <TableCell key={m.key} className="tabular text-right">
                  {formatMetricValue(row.values[index], m)}
                </TableCell>
              ))}
              {comparison &&
                result.metrics.map((m, index) => (
                  <TableCell key={`${m.key}-p`} className="tabular text-right">
                    {formatMetricValue(row.previous?.[index], m)} ·{' '}
                    {formatVariation(variation(row.values[index], row.previous?.[index]))}
                  </TableCell>
                ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/** Os mesmos números do gráfico, para leitores de tela. */
function ScreenReaderTable({ result, title }: { result: AggregateResult; title: string }) {
  const { points, series } = chartData(result, true)
  // O sr-only fica num div: em <table>, a largura cresce com o conteúdo e vaza da página.
  return (
    <div className="sr-only">
      <table>
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">{result.dimension?.column ?? 'Grupo'}</th>
            {series.map((s) => (
              <th key={s.key} scope="col">
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.label}>
              <th scope="row">{p.label}</th>
              {series.map((s) => (
                <td key={s.key}>{formatMetricValue(p[`raw_${s.key}`], s.metric)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
