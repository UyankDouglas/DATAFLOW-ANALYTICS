import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Loader2, MailCheck } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Field } from '@/components/field'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { authApi } from '@/features/auth/api'
import {
  forgotSchema,
  PASSWORD_MIN,
  resetSchema,
  type ForgotValues,
  type ResetValues,
} from '@/features/auth/schemas'
import { describeError } from '@/services/api-client'

export function ForgotPasswordPage() {
  const forgot = useMutation({ mutationFn: (email: string) => authApi.forgotPassword(email) })
  const form = useForm<ForgotValues>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: '' },
  })

  if (forgot.isSuccess) {
    return (
      <div className="animate-fade-in text-center">
        <MailCheck className="mx-auto size-10 text-success" aria-hidden />
        <h1 className="mt-4 text-xl font-semibold">Verifique seu e-mail</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {forgot.data.message} O link expira em 30 minutos.
        </p>
        <Button asChild variant="outline" className="mt-6">
          <Link to="/entrar">Voltar ao login</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <h1 className="text-2xl font-semibold tracking-tight">Recuperar senha</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Enviaremos um link de redefinição para o seu e-mail.
      </p>
      {forgot.isError && (
        <Alert variant="destructive" className="mt-6">
          <AlertDescription>{describeError(forgot.error)}</AlertDescription>
        </Alert>
      )}
      <form
        onSubmit={form.handleSubmit(({ email }) => forgot.mutate(email))}
        className="mt-6 space-y-4"
        noValidate
      >
        <Field label="E-mail" error={form.formState.errors.email?.message}>
          {(props) => (
            <Input {...props} type="email" autoComplete="email" {...form.register('email')} />
          )}
        </Field>
        <Button type="submit" className="w-full" disabled={forgot.isPending}>
          {forgot.isPending && <Loader2 className="animate-spin" />}
          Enviar link
        </Button>
      </form>
      <p className="mt-6 text-center text-sm">
        <Link to="/entrar" className="text-primary hover:underline">
          Voltar ao login
        </Link>
      </p>
    </div>
  )
}

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const navigate = useNavigate()
  const reset = useMutation({
    mutationFn: (password: string) => authApi.resetPassword(token, password),
  })
  const form = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: '', confirm_password: '' },
  })
  const { errors } = form.formState

  if (!token) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          Link inválido. Solicite uma nova redefinição em{' '}
          <Link to="/recuperar-senha" className="underline">
            Recuperar senha
          </Link>
          .
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="animate-fade-in">
      <h1 className="text-2xl font-semibold tracking-tight">Redefinir senha</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Todas as sessões abertas serão encerradas.
      </p>
      {reset.isError && (
        <Alert variant="destructive" className="mt-6">
          <AlertDescription>{describeError(reset.error)}</AlertDescription>
        </Alert>
      )}
      <form
        onSubmit={form.handleSubmit(({ password }) =>
          reset.mutate(password, {
            onSuccess: () => {
              toast.success('Senha redefinida. Entre com a nova senha.', {
                icon: <CheckCircle2 className="size-4" />,
              })
              navigate('/entrar', { replace: true })
            },
          }),
        )}
        className="mt-6 space-y-4"
        noValidate
      >
        <Field
          label="Nova senha"
          error={errors.password?.message}
          hint={`Mínimo de ${PASSWORD_MIN} caracteres.`}
        >
          {(props) => (
            <Input
              {...props}
              type="password"
              autoComplete="new-password"
              {...form.register('password')}
            />
          )}
        </Field>
        <Field label="Confirmar nova senha" error={errors.confirm_password?.message}>
          {(props) => (
            <Input
              {...props}
              type="password"
              autoComplete="new-password"
              {...form.register('confirm_password')}
            />
          )}
        </Field>
        <Button type="submit" className="w-full" disabled={reset.isPending}>
          {reset.isPending && <Loader2 className="animate-spin" />}
          Redefinir senha
        </Button>
      </form>
    </div>
  )
}
