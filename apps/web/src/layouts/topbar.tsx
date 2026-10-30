import { useQuery } from '@tanstack/react-query'
import {
  Bell,
  Building2,
  Check,
  ChevronsUpDown,
  LogOut,
  Menu,
  Moon,
  PanelLeft,
  Sun,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { StatusBadge } from '@/components/status-badge'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { authApi } from '@/features/auth/api'
import { useLogout, useSession, useSwitchWorkspace } from '@/features/auth/use-auth'
import { jobsApi } from '@/features/jobs/api'
import { JOB_STATUS_LABEL, JOB_STATUS_TONE, isActive } from '@/features/jobs/status'
import { useTheme } from '@/hooks/use-theme'
import { formatRelative } from '@/lib/format'
import { describeError } from '@/services/api-client'

const ROLE_LABEL = { admin: 'Administrador', analyst: 'Analista', viewer: 'Visualizador' } as const

interface TopbarProps {
  onToggleSidebar: () => void
  onOpenMobileNav: () => void
}

export function Topbar({ onToggleSidebar, onOpenMobileNav }: TopbarProps) {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-1 border-b bg-background/80 px-3 backdrop-blur sm:gap-2 sm:px-5">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        onClick={onOpenMobileNav}
        aria-label="Abrir menu"
      >
        <Menu />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="hidden lg:inline-flex"
        onClick={onToggleSidebar}
        aria-label="Recolher ou expandir menu lateral"
      >
        <PanelLeft />
      </Button>
      <WorkspaceSwitcher />
      <div className="flex-1" />
      <Notifications />
      <ThemeToggle />
      <UserMenu />
    </header>
  )
}

function WorkspaceSwitcher() {
  const { data: session } = useSession()
  const switchWorkspace = useSwitchWorkspace()
  const workspaces = useQuery({
    queryKey: ['auth', 'workspaces'],
    queryFn: authApi.workspaces,
    staleTime: 60_000,
  })
  const current = session?.workspace

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="max-w-[42vw] min-w-0 shrink gap-2 px-2 sm:max-w-xs"
          aria-label="Trocar de workspace"
        >
          <span className="rounded-md bg-primary/12 p-1 text-primary">
            <Building2 className="size-4" />
          </span>
          <span className="min-w-0 text-left">
            <span className="block truncate text-sm font-medium">
              {current?.name ?? 'Sem workspace'}
            </span>
          </span>
          <ChevronsUpDown className="size-3.5 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
        {workspaces.data?.map((ws) => (
          <DropdownMenuItem
            key={ws.id}
            onSelect={() => {
              if (ws.id === current?.id) return
              switchWorkspace.mutate(ws.id, {
                onSuccess: () => toast.success(`Workspace alterado para ${ws.name}.`),
                onError: (error) => toast.error(describeError(error)),
              })
            }}
          >
            <span className="flex-1 truncate">{ws.name}</span>
            <span className="text-xs text-muted-foreground">{ROLE_LABEL[ws.role]}</span>
            {ws.id === current?.id && <Check className="size-4" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Notificações reais: últimos processamentos do workspace. */
function Notifications() {
  const navigate = useNavigate()
  const jobs = useQuery({
    queryKey: ['jobs', 'notifications'],
    queryFn: () => jobsApi.list({ page: 1, pageSize: 6 }),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => isActive(job.status)) ? 3000 : 30_000,
  })
  const items = jobs.data?.items ?? []
  const active = items.filter((job) => isActive(job.status)).length

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={`Notificações${active ? `, ${active} em andamento` : ''}`}
        >
          <Bell />
          {active > 0 && (
            <span className="absolute top-2 right-2 size-2 animate-pulse rounded-full bg-primary" />
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Processamentos recentes</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 && (
          <p className="px-2 py-4 text-center text-sm text-muted-foreground">
            Nenhum processamento ainda.
          </p>
        )}
        {items.map((job) => (
          <DropdownMenuItem
            key={job.id}
            onSelect={() => navigate(`/processamentos/${job.id}`)}
            className="flex-col items-start gap-1"
          >
            <span className="flex w-full items-center justify-between gap-2">
              <span className="truncate text-sm font-medium">{job.dataset_name}</span>
              <StatusBadge tone={JOB_STATUS_TONE[job.status]} pulse={isActive(job.status)}>
                {JOB_STATUS_LABEL[job.status]}
              </StatusBadge>
            </span>
            <span className="text-xs text-muted-foreground">
              {formatRelative(job.finished_at ?? job.created_at)}
            </span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/processamentos" className="justify-center text-sm">
            Ver histórico completo
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ThemeToggle() {
  const { theme, toggle } = useTheme()
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label={theme === 'dark' ? 'Ativar tema claro' : 'Ativar tema escuro'}
    >
      {theme === 'dark' ? <Sun /> : <Moon />}
    </Button>
  )
}

function UserMenu() {
  const { data: session } = useSession()
  const logout = useLogout()
  const navigate = useNavigate()
  const user = session?.user
  const initials = (user?.full_name ?? '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="gap-2 px-1.5" aria-label="Menu do usuário">
          <Avatar className="size-8">
            <AvatarFallback className="bg-primary/15 text-xs font-semibold text-primary">
              {initials}
            </AvatarFallback>
          </Avatar>
          <span className="hidden text-left md:block">
            <span className="block max-w-36 truncate text-sm leading-tight font-medium">
              {user?.full_name}
            </span>
            <span className="block text-xs leading-tight text-muted-foreground">
              {session?.workspace ? ROLE_LABEL[session.workspace.role] : ''}
            </span>
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate font-medium">{user?.full_name}</span>
          <span className="block truncate text-xs text-muted-foreground">{user?.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() =>
            logout.mutate(undefined, {
              onSettled: () => {
                toast.success('Sessão encerrada.')
                navigate('/entrar', { replace: true })
              },
            })
          }
        >
          <LogOut /> Sair
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
