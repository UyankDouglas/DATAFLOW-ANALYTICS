import { cn } from '@/lib/utils'

/** Marca: fluxo de dados em três camadas convergindo para um ponto (pipeline). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn('size-8', className)} aria-hidden>
      <defs>
        <linearGradient id="df-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3B82F6" />
          <stop offset="0.55" stopColor="#06B6D4" />
          <stop offset="1" stopColor="#8B5CF6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#df-grad)" />
      <path
        d="M8 10h9a4 4 0 0 1 4 4"
        stroke="#F8FAFC"
        strokeWidth="2.4"
        fill="none"
        strokeLinecap="round"
      />
      <path d="M8 16h13" stroke="#F8FAFC" strokeWidth="2.4" strokeLinecap="round" />
      <path
        d="M8 22h9a4 4 0 0 0 4-4"
        stroke="#F8FAFC"
        strokeWidth="2.4"
        fill="none"
        strokeLinecap="round"
      />
      <circle cx="24" cy="16" r="2.6" fill="#F8FAFC" />
    </svg>
  )
}

export function Logo({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      {!collapsed && (
        <span className="leading-tight">
          <span className="block text-sm font-semibold tracking-tight">DataFlow</span>
          <span className="block text-[11px] tracking-wide text-muted-foreground uppercase">
            Analytics
          </span>
        </span>
      )}
    </span>
  )
}
