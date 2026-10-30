import { cn } from '@/lib/utils'
import type { Tone } from '@/features/jobs/status'

const TONE_CLASS: Record<Tone, string> = {
  neutral: 'bg-muted text-muted-foreground border-border',
  info: 'bg-info/12 text-info border-info/25',
  primary: 'bg-primary/12 text-primary border-primary/25',
  success: 'bg-success/12 text-success border-success/25',
  warning: 'bg-warning/12 text-warning border-warning/25',
  danger: 'bg-destructive/12 text-destructive border-destructive/25',
}

interface StatusBadgeProps {
  tone: Tone
  children: React.ReactNode
  pulse?: boolean
  className?: string
}

export function StatusBadge({ tone, children, pulse, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap',
        TONE_CLASS[tone],
        className,
      )}
    >
      <span
        className={cn('size-1.5 rounded-full bg-current', pulse && 'animate-pulse')}
        aria-hidden
      />
      {children}
    </span>
  )
}
