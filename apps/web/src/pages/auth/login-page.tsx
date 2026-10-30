import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate } from 'react-router'

import { Field } from '@/components/field'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { loginSchema, type LoginValues } from '@/features/auth/schemas'
import { useLogin } from '@/features/auth/use-auth'
import { describeError } from '@/services/api-client'

export function LoginPage() {
  const login = useLogin()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })
  const { errors } = form.formState

  const onSubmit = form.handleSubmit((values) =>
    login.mutate(values, { onSuccess: () => navigate(from, { replace: true }) }),
  )

  return (
    <div className="animate-fade-in">
      <h1 className="text-2xl font-semibold tracking-tight">Entrar</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Acesse seu workspace no DataFlow Analytics.
      </p>

      {login.isError && (
        <Alert variant="destructive" className="mt-6">
          <AlertDescription>{describeError(login.error)}</AlertDescription>
        </Alert>
      )}

      <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
        <Field label="E-mail" error={errors.email?.message}>
          {(props) => (
            <Input {...props} type="email" autoComplete="email" {...form.register('email')} />
          )}
        </Field>
        <Field label="Senha" error={errors.password?.message}>
          {(props) => (
            <Input
              {...props}
              type="password"
              autoComplete="current-password"
              {...form.register('password')}
            />
          )}
        </Field>
        <div className="flex justify-end">
          <Link to="/recuperar-senha" className="text-sm text-primary hover:underline">
            Esqueci minha senha
          </Link>
        </div>
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending && <Loader2 className="animate-spin" />}
          Entrar
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Ainda não tem conta?{' '}
        <Link to="/cadastro" className="font-medium text-primary hover:underline">
          Criar conta
        </Link>
      </p>
    </div>
  )
}
