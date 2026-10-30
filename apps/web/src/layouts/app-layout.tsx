import { useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'

import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/states'
import { useSession } from '@/features/auth/use-auth'
import { cn } from '@/lib/utils'

import { SidebarNav } from './sidebar'
import { Topbar } from './topbar'

const COLLAPSE_KEY = 'df-sidebar-collapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

export function AppLayout() {
  const session = useSession()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)

  if (session.isPending) return <AppSplash />
  if (session.isError) {
    return (
      <div className="grid min-h-svh place-items-center p-6">
        <ErrorState
          error={session.error}
          onRetry={() => session.refetch()}
          title="Não foi possível validar sua sessão"
        />
      </div>
    )
  }
  if (!session.data) {
    return <Navigate to="/entrar" replace state={{ from: location.pathname + location.search }} />
  }

  const toggle = () => {
    setCollapsed((value) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, value ? '0' : '1')
      } catch {
        // preferência apenas nesta sessão
      }
      return !value
    })
  }

  return (
    <div className="flex min-h-svh">
      <a
        href="#conteudo"
        className="sr-only z-50 rounded-md px-3 py-2 focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:bg-primary focus:text-primary-foreground"
      >
        Pular para o conteúdo
      </a>
      <aside
        className={cn(
          'sticky top-0 hidden h-svh shrink-0 border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 lg:block',
          collapsed ? 'w-[72px]' : 'w-70',
        )}
      >
        <SidebarNav collapsed={collapsed} />
      </aside>
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-72 bg-sidebar p-0">
          <SheetTitle className="sr-only">Menu</SheetTitle>
          <SheetDescription className="sr-only">
            Navegação principal do DataFlow Analytics
          </SheetDescription>
          <SidebarNav onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onToggleSidebar={toggle} onOpenMobileNav={() => setMobileOpen(true)} />
        <main
          id="conteudo"
          className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8"
        >
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function AppSplash() {
  return (
    <div className="flex min-h-svh" aria-busy="true" aria-label="Carregando aplicação">
      <div className="hidden w-70 border-r bg-sidebar p-4 lg:block">
        <Skeleton className="h-8 w-36" />
        <div className="mt-8 space-y-2">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      </div>
      <div className="flex-1 p-6">
        <Skeleton className="h-8 w-64" />
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      </div>
    </div>
  )
}
