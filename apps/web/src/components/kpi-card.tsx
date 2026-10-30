import type { LucideIcon } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const ACCENTS = {
  blue: 'text-primary bg-primary/10 ring-primary/20',
  cyan: 'text-info bg-info/10 ring-info/20',
  violet: 'text-violet bg-violet/10 ring-violet/20',
  green: 'text-success bg-success/10 ring-success/20',
  amber: 'text-warning bg-warning/10 ring-warning/20',
  red: 'text-destructive bg-destructive/10 ring-destructive/20',
} as const

interface KpiCardProps {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  icon: LucideIcon
  accent?: keyof typeof ACCENTS
  loading?: boolean
}

export function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  accent = 'blue',
  loading,
}: KpiCardProps) {
  return (
    <Card className="animate-fade-in gap-0 p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        <span className={cn('rounded-lg p-2 ring-1', ACCENTS[accent])}>
          <Icon className="size-4" aria-hidden />
        </span>
      </div>
      {loading ? (
        <Skeleton className="mt-3 h-8 w-24" />
      ) : (
        <p className="tabular mt-2 text-2xl font-semibold tracking-tight">{value}</p>
      )}
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  )
}
