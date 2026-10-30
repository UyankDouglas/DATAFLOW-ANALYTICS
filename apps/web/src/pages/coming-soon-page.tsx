import { Construction, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router'

import { PageHeader } from '@/components/page-header'
import { EmptyState } from '@/components/states'
import { Button } from '@/components/ui/button'

interface ComingSoonPageProps {
  title: string
  phase: number
  description: string
  icon: LucideIcon
}

/** Módulos ainda não implementados: estado explícito, sem simular funcionalidade. */
export function ComingSoonPage({ title, phase, description, icon }: ComingSoonPageProps) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <EmptyState
        icon={icon ?? Construction}
        title="Em desenvolvimento"
        description={
          <>
            Este módulo será entregue na <strong>Fase {phase}</strong> do roadmap. Nenhuma operação
            desta tela está disponível ainda.
          </>
        }
        action={
          <Button asChild variant="outline">
            <Link to="/datasets">Ir para datasets</Link>
          </Button>
        }
      />
    </>
  )
}
