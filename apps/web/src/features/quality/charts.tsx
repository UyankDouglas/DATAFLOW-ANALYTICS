import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { REJECTION_LABEL } from '@/features/jobs/status'
import { CATEGORY_LABEL } from '@/features/transformations/rules'
import { formatInteger } from '@/lib/format'
import type {
  ExclusionCategory,
  QualityColumnProfile,
  QualityIssue,
  QualityVersionSummary,
} from '@/types/api'

import { formatRatio, formatScore } from './score'

const AXIS = { fill: 'var(--muted-foreground)', fontSize: 12 }
const TOOLTIP = {
  background: 'var(--popover)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  color: 'var(--popover-foreground)',
}
const CATEGORY_COLOR: Record<ExclusionCategory, string> = {
  rejeitado: 'var(--warning)',
  filtrado: 'var(--chart-2)',
  duplicado: 'var(--chart-3)',
}

/** Completude de cada coluna, da menos para a mais completa. */
export function CompletenessChart({ columns }: { columns: QualityColumnProfile[] }) {
  const data = [...columns]
    .map((c) => ({ name: c.name, value: (c.completeness ?? 0) * 100, nulls: c.nulls }))
    .sort((a, b) => a.value - b.value)
  return (
    <ResponsiveContainer width="100%" height={Math.max(160, data.length * 28)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis
          type="number"
          domain={[0, 100]}
          unit="%"
          tick={AXIS}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          width={120}
          tick={AXIS}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          cursor={{ fill: 'var(--accent)', opacity: 0.4 }}
          contentStyle={TOOLTIP}
          formatter={(value, _name, item) => [
            `${formatRatio(Number(value) / 100)} · ${formatInteger((item.payload as { nulls: number }).nulls)} nulos`,
            'Completude',
          ]}
        />
        <Bar dataKey="value" name="Completude" fill="var(--chart-4)" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Quantos registros publicados têm 0, 1, 2… colunas nulas. */
export function NullDistributionChart({ data }: { data: { nulls: number; rows: number }[] }) {
  const rows = data.map((d) => ({
    label: `${d.nulls} nula${d.nulls === 1 ? '' : 's'}`,
    rows: d.rows,
  }))
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} />
        <Tooltip
          cursor={{ fill: 'var(--accent)', opacity: 0.4 }}
          contentStyle={TOOLTIP}
          formatter={(value) => [formatInteger(Number(value)), 'Registros']}
        />
        <Bar dataKey="rows" name="Registros" fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Exclusões por motivo, coloridas pela categoria. */
export function IssuesChart({ issues }: { issues: QualityIssue[] }) {
  const grouped = new Map<string, { label: string; category: ExclusionCategory; count: number }>()
  for (const issue of issues) {
    const key = `${issue.category}:${issue.reason}`
    const current = grouped.get(key)
    if (current) current.count += issue.count
    else
      grouped.set(key, {
        label: REJECTION_LABEL[issue.reason] ?? issue.reason,
        category: issue.category,
        count: issue.count,
      })
  }
  const data = [...grouped.values()].sort((a, b) => b.count - a.count)
  return (
    <ResponsiveContainer width="100%" height={Math.max(160, data.length * 32)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis
          type="category"
          dataKey="label"
          width={160}
          tick={AXIS}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          cursor={{ fill: 'var(--accent)', opacity: 0.4 }}
          contentStyle={TOOLTIP}
          formatter={(value, _name, item) => [
            formatInteger(Number(value)),
            CATEGORY_LABEL[(item.payload as { category: ExclusionCategory }).category],
          ]}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {data.map((entry) => (
            <Cell key={`${entry.category}-${entry.label}`} fill={CATEGORY_COLOR[entry.category]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Nota por versão; versões sem relatório ficam de fora da linha. */
export function VersionScoreChart({ versions }: { versions: QualityVersionSummary[] }) {
  const data = versions
    .filter((v) => v.computed && v.score !== null)
    .map((v) => ({ label: `v${v.version_number}`, score: v.score }))
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis domain={[0, 100]} tick={AXIS} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={TOOLTIP}
          formatter={(value) => [formatScore(Number(value)), 'Nota']}
        />
        <Line
          type="monotone"
          dataKey="score"
          name="Nota"
          stroke="var(--chart-1)"
          strokeWidth={2}
          dot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

/** Valores mais frequentes de uma coluna. */
export function FrequencyChart({ values }: { values: { value: unknown; count: number }[] }) {
  const data = values.map((v) => ({ label: String(v.value), count: v.count }))
  return (
    <ResponsiveContainer width="100%" height={Math.max(160, data.length * 28)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis
          type="category"
          dataKey="label"
          width={140}
          tick={AXIS}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          cursor={{ fill: 'var(--accent)', opacity: 0.4 }}
          contentStyle={TOOLTIP}
          formatter={(value) => [formatInteger(Number(value)), 'Registros']}
        />
        <Bar dataKey="count" fill="var(--chart-5)" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
