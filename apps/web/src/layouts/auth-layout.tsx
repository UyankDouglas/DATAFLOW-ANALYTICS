import { CheckCircle2, Database, FileCheck2, GitBranch, Workflow } from 'lucide-react'
import { Navigate, Outlet } from 'react-router'

import { LogoMark } from '@/components/logo'
import { useSession } from '@/features/auth/use-auth'

const STAGES = [
  { icon: FileCheck2, label: 'Upload validado', detail: 'Extensão, conteúdo real e limites' },
  {
    icon: Workflow,
    label: 'Pipeline assíncrono',
    detail: 'Progresso medido em trabalho concluído',
  },
  { icon: GitBranch, label: 'Versões imutáveis', detail: 'Parquet versionado e rastreável' },
  { icon: Database, label: 'Consultas controladas', detail: 'DuckDB sem SQL arbitrário' },
]

export function AuthLayout({ guestOnly = true }: { guestOnly?: boolean }) {
  const session = useSession()
  if (guestOnly && session.data) return <Navigate to="/" replace />

  return (
    <div className="grid min-h-svh lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden overflow-hidden border-r bg-sidebar lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="bg-grid absolute inset-0 opacity-60" aria-hidden />
        <div
          className="absolute -top-24 -left-24 size-96 rounded-full bg-primary/25 blur-3xl"
          aria-hidden
        />
        <div
          className="absolute -right-20 bottom-0 size-80 rounded-full bg-violet/20 blur-3xl"
          aria-hidden
        />
        <div className="relative flex items-center gap-3">
          <LogoMark className="size-10" />
          <div>
            <p className="text-lg font-semibold tracking-tight">DataFlow Analytics</p>
            <p className="text-sm text-muted-foreground">Engenharia de dados e BI</p>
          </div>
        </div>
        <div className="relative max-w-md">
          <h2 className="text-3xl leading-tight font-semibold tracking-tight">
            De planilhas brutas a{' '}
            <span className="bg-gradient-to-r from-primary via-info to-violet bg-clip-text text-transparent">
              dados confiáveis
            </span>
            .
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            Cada registro recebido é contabilizado: válidos, rejeitados e o motivo de cada rejeição.
            Nada é descartado em silêncio.
          </p>
          <ol className="mt-8 space-y-3">
            {STAGES.map(({ icon: Icon, label, detail }) => (
              <li
                key={label}
                className="flex items-center gap-3 rounded-xl border bg-card/60 p-3 backdrop-blur"
              >
                <span className="rounded-lg bg-primary/12 p-2 text-primary">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="flex-1">
                  <span className="block text-sm font-medium">{label}</span>
                  <span className="block text-xs text-muted-foreground">{detail}</span>
                </span>
                <CheckCircle2 className="size-4 text-success" aria-hidden />
              </li>
            ))}
          </ol>
        </div>
        <p className="relative text-xs text-muted-foreground">
          Projeto de portfólio · dados de demonstração são fictícios.
        </p>
      </section>
      <section className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <LogoMark />
            <span className="font-semibold">DataFlow Analytics</span>
          </div>
          <Outlet />
        </div>
      </section>
    </div>
  )
}
