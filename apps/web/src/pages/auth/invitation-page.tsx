import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, MailCheck } from 'lucide-react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { membersApi } from '@/features/admin/api'
import { ROLE_INFO } from '@/features/admin/labels'
import { ME_KEY, useSession } from '@/features/auth/use-auth'
import { formatTimestamp } from '@/lib/format'
import { describeError } from '@/services/api-client'

/** Abre o link do convite: mostra o workspace e aceita com a conta do e-mail convidado. */
export function InvitationPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const location = useLocation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const session = useSession()
  const preview = useQuery({
    queryKey: ['invitation', token],
    queryFn: () => membersApi.previewInvitation(token),
    enabled: token.length > 0,
    retry: false,
  })
  const accept = useMutation({
    mutationFn: () => membersApi.acceptInvitation(token),
    onSuccess: () => {
      client.clear()
      client.invalidateQueries({ queryKey: ME_KEY })
      toast.success(`Você entrou no workspace ${preview.data?.workspace_name ?? ''}.`)
      navigate('/', { replace: true })
    },
  })
  const back = { from: location.pathname + location.search }

  return (
    <div className="animate-fade-in space-y-5">
      <div className="flex items-center gap-3">
        <span className="rounded-xl bg-primary/10 p-2.5 text-primary ring-1 ring-primary/20">
          <MailCheck className="size-5" aria-hidden />
        </span>
        <h1 className="text-2xl font-semibold tracking-tight">Convite para um workspace</h1>
      </div>
      {!token ? (
        <Alert variant="destructive">
          <AlertDescription>
            Link de convite incompleto. Abra o link do e-mail de novo.
          </AlertDescription>
        </Alert>
      ) : preview.isPending ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Conferindo o convite…
        </p>
      ) : preview.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{describeError(preview.error)}</AlertDescription>
        </Alert>
      ) : (
        <>
          <dl className="space-y-2 rounded-xl border p-4 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Workspace</dt>
              <dd className="font-medium">{preview.data.workspace_name}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Perfil</dt>
              <dd>{ROLE_INFO[preview.data.role].label}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Para o e-mail</dt>
              <dd className="break-all">{preview.data.email}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Válido até</dt>
              <dd className="tabular">{formatTimestamp(preview.data.expires_at)}</dd>
            </div>
          </dl>
          {accept.isError && (
            <Alert variant="destructive">
              <AlertDescription>{describeError(accept.error)}</AlertDescription>
            </Alert>
          )}
          {session.data ? (
            <div className="space-y-3">
              {session.data.user.email.toLowerCase() !== preview.data.email && (
                <p className="text-sm text-muted-foreground">
                  Você está conectado como <strong>{session.data.user.email}</strong>. O convite só
                  pode ser aceito com a conta de {preview.data.email}.
                </p>
              )}
              <Button
                className="w-full"
                disabled={accept.isPending}
                onClick={() => accept.mutate()}
              >
                {accept.isPending && <Loader2 className="animate-spin" />} Aceitar convite
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Entre com a conta de {preview.data.email} ou crie uma com esse e-mail. Depois você
                volta para esta página para aceitar.
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                <Button asChild>
                  <Link to="/entrar" state={back}>
                    Entrar
                  </Link>
                </Button>
                <Button asChild variant="outline">
                  <Link to="/cadastro" state={back}>
                    Criar conta
                  </Link>
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
