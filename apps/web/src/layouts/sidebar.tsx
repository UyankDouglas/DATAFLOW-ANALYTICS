import { NavLink } from 'react-router'

import { Logo } from '@/components/logo'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSession } from '@/features/auth/use-auth'
import { cn } from '@/lib/utils'
import { NAV_GROUPS, type NavItem } from '@/routes/nav'

interface SidebarNavProps {
  collapsed?: boolean
  onNavigate?: () => void
}

export function SidebarNav({ collapsed = false, onNavigate }: SidebarNavProps) {
  const { data: session } = useSession()
  const permissions = session?.permissions ?? []
  const visible = (item: NavItem) => !item.permission || permissions.includes(item.permission)

  return (
    <div className="flex h-full flex-col">
      <div
        className={cn(
          'flex h-16 items-center border-b border-sidebar-border px-4',
          collapsed && 'justify-center px-2',
        )}
      >
        <NavLink to="/" onClick={onNavigate} aria-label="DataFlow Analytics — início">
          <Logo collapsed={collapsed} />
        </NavLink>
      </div>
      <nav aria-label="Navegação principal" className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter(visible)
          if (items.length === 0) return null
          return (
            <div key={group.label}>
              {!collapsed && (
                <p className="mb-1.5 px-2 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">
                  {group.label}
                </p>
              )}
              <ul className="space-y-0.5">
                {items.map((item) => (
                  <li key={item.to}>
                    <SidebarLink item={item} collapsed={collapsed} onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </nav>
      {!collapsed && (
        <div className="border-t border-sidebar-border px-4 py-3 text-[11px] text-muted-foreground">
          Fase 1 · Fundação e primeiro dataset
        </div>
      )}
    </div>
  )
}

function SidebarLink({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem
  collapsed: boolean
  onNavigate?: () => void
}) {
  const Icon = item.icon
  const link = (
    <NavLink
      to={item.to}
      end={item.to === '/' || item.to === '/dashboards'}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'group relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors outline-none',
          'focus-visible:ring-2 focus-visible:ring-sidebar-ring',
          isActive
            ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
            : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground',
          collapsed && 'justify-center px-2',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-primary"
              aria-hidden
            />
          )}
          <Icon
            className={cn('size-4 shrink-0', isActive ? 'text-primary' : 'opacity-80')}
            aria-hidden
          />
          {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
          {!collapsed && item.phase && (
            <span className="rounded border border-sidebar-border px-1.5 py-px text-[10px] text-muted-foreground">
              Em breve
            </span>
          )}
          {collapsed && <span className="sr-only">{item.label}</span>}
        </>
      )}
    </NavLink>
  )
  if (!collapsed) return link
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">
        {item.label}
        {item.phase ? ' (em breve)' : ''}
      </TooltipContent>
    </Tooltip>
  )
}
