import { expect, test, type APIRequestContext } from '@playwright/test'

import { newUser, register } from './helpers'

// Vazio desativa o teste: o Compose de produção não tem Mailpit.
const MAILPIT = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025'

/** Busca no Mailpit o e-mail realmente entregue pelo worker via SMTP. */
async function findResetLink(request: APIRequestContext, email: string): Promise<string> {
  const query = encodeURIComponent(`to:"${email}"`)
  let link = ''
  await expect(async () => {
    const search = await (await request.get(`${MAILPIT}/api/v1/search?query=${query}`)).json()
    expect(search.messages?.length ?? 0).toBeGreaterThan(0)
    const message = await (
      await request.get(`${MAILPIT}/api/v1/message/${search.messages[0].ID}`)
    ).json()
    expect(message.Subject).toBe('Redefinição de senha — DataFlow Analytics')
    const match = /https?:\/\/\S+\/redefinir-senha\?token=\S+/.exec(message.Text)
    expect(match, 'link de redefinição no corpo do e-mail').not.toBeNull()
    link = match?.[0] ?? ''
  }).toPass({ timeout: 30_000 })
  return link
}

test('recuperação de senha: e-mail real, troca de senha e sessões encerradas', async ({
  browser,
  request,
  baseURL,
}) => {
  const reachable = MAILPIT
    ? await request.get(`${MAILPIT}/api/v1/info`).then(
        (response) => response.ok(),
        () => false,
      )
    : false
  // Na CI o Mailpit é obrigatório no ambiente de desenvolvimento: se faltar, o teste falha.
  test.skip(!MAILPIT || (!reachable && !process.env.CI), 'requer o Mailpit do Docker Compose')

  const user = newUser('Email')
  const loggedInContext = await browser.newContext()
  const loggedIn = await loggedInContext.newPage()
  await register(loggedIn, user)

  const anonContext = await browser.newContext()
  const anon = await anonContext.newPage()
  await anon.goto('/recuperar-senha')
  await anon.getByLabel('E-mail').fill(user.email)
  await anon.getByRole('button', { name: 'Enviar link' }).click()
  await expect(anon.getByRole('heading', { name: 'Verifique seu e-mail' })).toBeVisible()

  const link = await findResetLink(request, user.email)
  expect(new URL(link).origin, 'link aponta para APP_BASE_URL').toBe(baseURL)

  const newPassword = `${user.password}-nova`
  await anon.goto(link)
  await anon.getByLabel('Nova senha', { exact: true }).fill(newPassword)
  await anon.getByLabel('Confirmar nova senha').fill(newPassword)
  await anon.getByRole('button', { name: 'Redefinir senha' }).click()
  await expect(anon).toHaveURL(/\/entrar/)

  // A sessão aberta antes da troca foi revogada no servidor.
  await loggedIn.goto('/')
  await expect(loggedIn).toHaveURL(/\/entrar/)

  // A senha antiga deixa de valer e a nova passa a valer.
  await anon.getByLabel('E-mail').fill(user.email)
  await anon.getByLabel('Senha').fill(user.password)
  await anon.getByRole('button', { name: 'Entrar' }).click()
  await expect(anon.getByText('E-mail ou senha inválidos.')).toBeVisible()
  await anon.getByLabel('Senha').fill(newPassword)
  await anon.getByRole('button', { name: 'Entrar' }).click()
  await expect(anon.getByRole('heading', { name: /Olá/ })).toBeVisible()

  // O link é de uso único.
  const replayContext = await browser.newContext()
  const replay = await replayContext.newPage()
  await replay.goto(link)
  await replay.getByLabel('Nova senha', { exact: true }).fill(`${newPassword}-2`)
  await replay.getByLabel('Confirmar nova senha').fill(`${newPassword}-2`)
  await replay.getByRole('button', { name: 'Redefinir senha' }).click()
  await expect(replay.getByText('Link de redefinição inválido ou expirado.')).toBeVisible()

  await Promise.all([loggedInContext.close(), anonContext.close(), replayContext.close()])
})
