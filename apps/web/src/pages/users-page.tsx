import { useQuery } from '@tanstack/react-query'
import { Info, Users } from 'lucide-react'

import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { authApi } from '@/features/auth/api'
import { formatTimestamp } from '@/lib/format'
import type { Role } from '@/types/api'

const ROLE: Record<
  Role,
  { label: string; tone: 'primary' | 'info' | 'neutral'; description: string }
> = {
  admin: {
    label: 'Administrador',
    tone: 'primary',
    description: 'Gerencia usuários, workspace, datasets e auditoria',
  },
  analyst: { label: 'Analista', tone: 'info', description: 'Importa, processa e exporta dados' },
  viewer: {
    label: 'Visualizador',
    tone: 'neutral',
    description: 'Consulta datasets e dashboards autorizados',
  },
}

export function UsersPage() {
  const members = useQuery({ queryKey: ['members'], queryFn: authApi.members })

  return (
    <>
      <PageHeader
        title="Usuários e permissões"
        description="Membros do workspace atual e seus perfis de acesso (RBAC aplicado no servidor)."
      />
      <Alert className="mb-6">
        <Info />
        <AlertDescription>
          Convites, alteração de perfis e remoção de membros chegam na Fase 5. Esta lista é somente
          leitura.
        </AlertDescription>
      </Alert>
      {members.isPending ? (
        <TableSkeleton rows={3} columns={4} />
      ) : members.isError ? (
        <ErrorState error={members.error} onRetry={() => members.refetch()} />
      ) : members.data.length === 0 ? (
        <EmptyState icon={Users} title="Nenhum membro" />
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow className="hover:bg-transparent">
                <TableHead>Nome</TableHead>
                <TableHead>E-mail</TableHead>
                <TableHead>Perfil</TableHead>
                <TableHead>Membro desde</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.data.map((member) => (
                <TableRow key={member.id}>
                  <TableCell className="font-medium">{member.full_name}</TableCell>
                  <TableCell className="text-muted-foreground">{member.email}</TableCell>
                  <TableCell>
                    <StatusBadge tone={ROLE[member.role].tone}>
                      {ROLE[member.role].label}
                    </StatusBadge>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {ROLE[member.role].description}
                    </p>
                  </TableCell>
                  <TableCell className="tabular">{formatTimestamp(member.joined_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  )
}
