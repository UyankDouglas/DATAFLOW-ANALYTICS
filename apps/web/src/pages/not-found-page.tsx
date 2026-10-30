import { Compass } from 'lucide-react'
import { Link } from 'react-router'

import { EmptyState } from '@/components/states'
import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <EmptyState
      icon={Compass}
      title="Página não encontrada"
      description="O endereço acessado não existe ou foi movido."
      action={
        <Button asChild>
          <Link to="/">Voltar à visão geral</Link>
        </Button>
      }
    />
  )
}
