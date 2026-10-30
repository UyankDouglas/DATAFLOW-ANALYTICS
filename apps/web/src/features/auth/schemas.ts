import { z } from 'zod'

export const PASSWORD_MIN = 10

export const passwordSchema = z
  .string()
  .min(PASSWORD_MIN, `A senha precisa ter ao menos ${PASSWORD_MIN} caracteres.`)
  .max(128, 'A senha pode ter no máximo 128 caracteres.')
  .refine((value) => new Set(value).size >= 4, 'A senha é repetitiva demais.')

const email = z.email('Informe um e-mail válido.').trim()

export const loginSchema = z.object({
  email,
  password: z.string().min(1, 'Informe a senha.'),
})

export const registerSchema = z
  .object({
    full_name: z.string().trim().min(2, 'Informe seu nome.').max(120),
    email,
    workspace_name: z.string().trim().min(2, 'Informe o nome do workspace.').max(120),
    password: passwordSchema,
    confirm_password: z.string(),
  })
  .refine((data) => data.password === data.confirm_password, {
    path: ['confirm_password'],
    message: 'As senhas não conferem.',
  })

export const forgotSchema = z.object({ email })

export const resetSchema = z
  .object({ password: passwordSchema, confirm_password: z.string() })
  .refine((data) => data.password === data.confirm_password, {
    path: ['confirm_password'],
    message: 'As senhas não conferem.',
  })

export type LoginValues = z.infer<typeof loginSchema>
export type RegisterValues = z.infer<typeof registerSchema>
export type ForgotValues = z.infer<typeof forgotSchema>
export type ResetValues = z.infer<typeof resetSchema>
