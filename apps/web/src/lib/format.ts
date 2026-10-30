/**
 * Formatação pt-BR orientada pelo tipo do dado. Decimais chegam da API como texto e são
 * formatados sem conversão para ponto flutuante (preserva precisão). Nenhuma coluna recebe
 * formatação monetária automaticamente.
 */

const integerFormatter = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })
const percentFormatter = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  maximumFractionDigits: 1,
})

export function formatInteger(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return groupDigits(value)
  return integerFormatter.format(value)
}

function groupDigits(digits: string): string {
  const negative = digits.startsWith('-')
  const raw = negative ? digits.slice(1) : digits
  const grouped = raw.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return negative ? `-${grouped}` : grouped
}

/** Formata um decimal recebido como texto ("1234.50") → "1.234,50", sem perder casas. */
export function formatDecimal(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const text = typeof value === 'number' ? String(value) : value
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text
  const [integerPart = '0', fraction] = text.split('.')
  const grouped = groupDigits(integerPart)
  return fraction !== undefined ? `${grouped},${fraction}` : grouped
}

/** "2025-01-31" → "31/01/2025" sem interpretar fuso horário. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  if (!match) return value
  return `${match[3]}/${match[2]}/${match[1]}`
}

/** Data e hora de um dado do dataset (sem fuso): exibida como registrada. */
export function formatNaiveDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(value)
  if (!match) return value
  const seconds = match[6] ? `:${match[6]}` : ''
  return `${match[3]}/${match[2]}/${match[1]} ${match[4]}:${match[5]}${seconds}`
}

/** Instantes do sistema (UTC) exibidos no fuso local do navegador. */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function formatRelative(value: string | null | undefined, now = Date.now()): string {
  if (!value) return '—'
  const diff = Math.round((new Date(value).getTime() - now) / 1000)
  const rtf = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' })
  const abs = Math.abs(diff)
  if (abs < 60) return rtf.format(diff, 'second')
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  return rtf.format(Math.round(diff / 86400), 'day')
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} ${units[unit]}`
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  const totalSeconds = ms / 1000
  if (totalSeconds < 60)
    return `${totalSeconds.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round(totalSeconds % 60)
  if (minutes < 60) return `${minutes} min ${seconds} s`
  const hours = Math.floor(minutes / 60)
  return `${hours} h ${minutes % 60} min`
}

export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return '—'
  return percentFormatter.format(ratio)
}

export function formatBoolean(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value ? 'Sim' : 'Não'
}
