import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Field } from '@/components/field'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PASSWORD_MIN, registerSchema, type RegisterValues } from '@/features/auth/schemas'
import { useRegister } from '@/features/auth/use-auth'
import { ApiError, describeError } from '@/services/api-client'

export function RegisterPage() {
  const register = useRegister()
  const navigate = useNavigate()
  const form = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      full_name: '',
      email: '',
      workspace_name: '',
      password: '',
      confirm_password: '',
    },
  })
  const { errors } = form.formState

  const onSubmit = form.handleSubmit(({ confirm_password: _confirm, ...values }) =>
    register.mutate(values, {
      onSuccess: (me) => {
        toast.success(`Bem-vindo(a), ${me.user.full_name.split(' ')[0]}! Workspace criado.`)
        navigate('/', { replace: true })
      },
      onError: (error) => {
        if (error instanceof ApiError) {
          for (const [field, message] of Object.entries(error.fieldErrors)) {
            form.setError(field as keyof RegisterValues, { message })
          }
        }
      },
    }),
  )

  return (
    <div className="animate-fade-in">
      <h1 className="text-2xl font-semibold tracking-tight">Criar conta</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Você será administrador(a) do novo workspace.
      </p>

      {register.isError && (
        <Alert variant="destructive" className="mt-6">
          <AlertDescription>{describeError(register.error)}</AlertDescription>
        </Alert>
      )}

      <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
        <Field label="Nome completo" error={errors.full_name?.message}>
          {(props) => <Input {...props} autoComplete="name" {...form.register('full_name')} />}
        </Field>
        <Field label="E-mail" error={errors.email?.message}>
          {(props) => (
            <Input {...props} type="email" autoComplete="email" {...form.register('email')} />
          )}
        </Field>
        <Field
          label="Nome do workspace"
          error={errors.workspace_name?.message}
          hint="Ex.: nome da empresa ou equipe."
        >
          {(props) => (
            <Input {...props} autoComplete="organization" {...form.register('workspace_name')} />
          )}
        </Field>
        <Field
          label="Senha"
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
        <Field label="Confirmar senha" error={errors.confirm_password?.message}>
          {(props) => (
            <Input
              {...props}
              type="password"
              autoComplete="new-password"
              {...form.register('confirm_password')}
            />
          )}
        </Field>
        <Button type="submit" className="w-full" disabled={register.isPending}>
          {register.isPending && <Loader2 className="animate-spin" />}
          Criar conta
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Já tem conta?{' '}
        <Link to="/entrar" className="font-medium text-primary hover:underline">
          Entrar
        </Link>
      </p>
    </div>
  )
}
