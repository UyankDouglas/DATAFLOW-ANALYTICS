import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailPlus, Trash2, Users } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { membersApi } from '@/features/admin/api'
import { ROLE_INFO } from '@/features/admin/labels'
import { authApi } from '@/features/auth/api'
import { usePermission, useSession } from '@/features/auth/use-auth'
import { formatRelative, formatTimestamp } from '@/lib/format'
import { describeError } from '@/services/api-client'
import type { Member, Role } from '@/types/api'

const ROLES: Role[] = ['admin', 'analyst', 'viewer']

function RoleSelect({
  value,
  onChange,
  label,
  disabled,
}: {
  value: Role
  onChange: (role: Role) => void
  label: string
  disabled?: boolean
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as Role)} disabled={disabled}>
      <SelectTrigger size="sm" className="w-44" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {ROLES.map((role) => (
          <SelectItem key={role} value={role}>
            {ROLE_INFO[role].label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function UsersPage() {
  const canManage = usePermission('members:manage')
  const session = useSession()
  const client = useQueryClient()
  const members = useQuery({ queryKey: ['members'], queryFn: authApi.members })
  const [removing, setRemoving] = useState<Member | null>(null)
  const changeRole = useMutation({
    mutationFn: ({ member, role }: { member: Member; role: Role }) =>
      membersApi.changeRole(member.id, role),
    onSuccess: (_, { member, role }) => {
      toast.success(`${member.full_name} agora é ${ROLE_INFO[role].label}.`)
      client.invalidateQueries({ queryKey: ['members'] })
      client.invalidateQueries({ queryKey: ['auth', 'me'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <>
      <PageHeader
        title="Usuários e permissões"
        description="Membros do workspace e seus perfis. O servidor aplica as permissões em cada requisição e não deixa o workspace sem administrador."
      />
      <div className="space-y-6">
        {canManage && <Invitations />}
        {members.isPending ? (
          <TableSkeleton rows={3} columns={4} />
        ) : members.isError ? (
          <ErrorState error={members.error} onRetry={() => members.refetch()} />
        ) : members.data.length === 0 ? (
          <EmptyState icon={Users} title="Nenhum membro" />
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <Table>
              <caption className="sr-only">Membros do workspace</caption>
              <TableHeader className="bg-muted/40">
                <TableRow className="hover:bg-transparent">
                  <TableHead>Nome</TableHead>
                  <TableHead>E-mail</TableHead>
                  <TableHead>Perfil</TableHead>
                  <TableHead>Membro desde</TableHead>
                  {canManage && <TableHead className="text-right">Ações</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.data.map((member) => {
                  const self = member.user_id === session.data?.user.id
                  return (
                    <TableRow key={member.id}>
                      <TableCell className="font-medium">
                        {member.full_name}
                        {self && <span className="ml-1 text-xs text-muted-foreground">(você)</span>}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{member.email}</TableCell>
                      <TableCell>
                        {canManage ? (
                          <RoleSelect
                            label={`Perfil de ${member.full_name}`}
                            value={member.role}
                            disabled={changeRole.isPending}
                            onChange={(role) => changeRole.mutate({ member, role })}
                          />
                        ) : (
                          <StatusBadge tone={ROLE_INFO[member.role].tone}>
                            {ROLE_INFO[member.role].label}
                          </StatusBadge>
                        )}
                        <p className="mt-1 text-xs text-muted-foreground">
                          {ROLE_INFO[member.role].description}
                        </p>
                      </TableCell>
                      <TableCell className="tabular">{formatTimestamp(member.joined_at)}</TableCell>
                      {canManage && (
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Remover ${member.full_name}`}
                            onClick={() => setRemoving(member)}
                          >
                            <Trash2 />
                          </Button>
                        </TableCell>
                      )}
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
      {removing && <RemoveMember member={removing} onClose={() => setRemoving(null)} />}
    </>
  )
}

function RemoveMember({ member, onClose }: { member: Member; onClose: () => void }) {
  const client = useQueryClient()
  const remove = useMutation({
    mutationFn: () => membersApi.remove(member.id),
    onSuccess: () => {
      toast.success(`${member.full_name} foi removido do workspace.`)
      client.invalidateQueries({ queryKey: ['members'] })
      onClose()
    },
    onError: (error) => toast.error(describeError(error)),
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Remover {member.full_name}?</DialogTitle>
          <DialogDescription>
            A pessoa perde o acesso a este workspace na próxima ação. A conta dela, os datasets e o
            histórico continuam; ela pode ser convidada de novo depois.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
            Remover do workspace
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Invitations() {
  const client = useQueryClient()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('analyst')
  const invitations = useQuery({ queryKey: ['invitations'], queryFn: membersApi.invitations })
  const invite = useMutation({
    mutationFn: () => membersApi.invite(email.trim(), role),
    onSuccess: () => {
      toast.success(`Convite enviado para ${email.trim()}.`)
      setEmail('')
      client.invalidateQueries({ queryKey: ['invitations'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })
  const revoke = useMutation({
    mutationFn: (id: string) => membersApi.revoke(id),
    onSuccess: () => {
      toast.success('Convite cancelado.')
      client.invalidateQueries({ queryKey: ['invitations'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Convidar pessoas</CardTitle>
        <CardDescription>
          A pessoa recebe um link por e-mail, válido por 7 dias, e entra (ou cria a conta) com esse
          mesmo e-mail para aceitar. O perfil vem do convite.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={(event) => {
            event.preventDefault()
            invite.mutate()
          }}
        >
          <div className="min-w-0 flex-1 space-y-1.5">
            <Label htmlFor="convite-email">E-mail</Label>
            <Input
              id="convite-email"
              type="email"
              required
              maxLength={255}
              value={email}
              placeholder="pessoa@empresa.com.br"
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Perfil</Label>
            <RoleSelect label="Perfil do convite" value={role} onChange={setRole} />
          </div>
          <Button type="submit" disabled={invite.isPending || !email.trim()}>
            <MailPlus /> Convidar
          </Button>
        </form>
        {invitations.data && invitations.data.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-medium">Convites pendentes</h3>
            <ul className="divide-y rounded-lg border">
              {invitations.data.map((invitation) => (
                <li
                  key={invitation.id}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
                >
                  <span className="min-w-0">
                    <span className="font-medium break-all">{invitation.email}</span>{' '}
                    <span className="text-muted-foreground">
                      · {ROLE_INFO[invitation.role].label} · expira{' '}
                      {formatRelative(invitation.expires_at)}
                    </span>
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(invitation.id)}
                  >
                    Cancelar convite
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
