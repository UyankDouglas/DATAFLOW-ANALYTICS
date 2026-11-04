import { expect, test, type APIRequestContext } from '@playwright/test'

import { newUser, register, submitRegistration, uploadSample, waitForJobSuccess } from './helpers'

// Vazio desativa o teste do convite: o Compose de produção não tem Mailpit.
const MAILPIT = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025'

async function findInvitationPath(request: APIRequestContext, email: string): Promise<string> {
  const query = encodeURIComponent(`to:"${email}"`)
  let path = ''
  await expect(async () => {
    const search = await (await request.get(`${MAILPIT}/api/v1/search?query=${query}`)).json()
    expect(search.messages?.length ?? 0).toBeGreaterThan(0)
    const message = await (
      await request.get(`${MAILPIT}/api/v1/message/${search.messages[0].ID}`)
    ).json()
    expect(message.Subject).toMatch(/^Convite para .+ — DataFlow Analytics$/)
    const match = /https?:\/\/[^/\s]+(\/convite\?token=\S+)/.exec(message.Text)
    expect(match, 'link do convite no corpo do e-mail').not.toBeNull()
    path = match?.[1] ?? ''
  }).toPass({ timeout: 30_000 })
  return path
}

test('convite por e-mail: cadastro pelo link, perfil do convite e auditoria', async ({
  page,
  browser,
  request,
}) => {
  const reachable = MAILPIT
    ? await request.get(`${MAILPIT}/api/v1/info`).then(
        (response) => response.ok(),
        () => false,
      )
    : false
  test.skip(!MAILPIT || (!reachable && !process.env.CI), 'requer o Mailpit do Docker Compose')

  const admin = newUser('Admin')
  await register(page, admin)
  const guest = newUser('Convidada')
  await page.goto('/usuarios')
  await page.getByLabel('E-mail').fill(guest.email)
  await page.getByRole('button', { name: /Convidar/ }).click()
  await expect(page.getByText(`Convite enviado para ${guest.email}.`)).toBeVisible()

  const invitation = await findInvitationPath(request, guest.email)
  const context = await browser.newContext()
  const guestPage = await context.newPage()
  await guestPage.goto(invitation)
  await expect(guestPage.getByText(admin.workspace)).toBeVisible()
  await guestPage.getByRole('link', { name: 'Criar conta' }).click()
  await submitRegistration(guestPage, guest)
  await expect(guestPage).toHaveURL(/\/convite\?token=/) // o cadastro volta para o convite
  await guestPage.getByRole('button', { name: /Aceitar convite/ }).click()
  await expect(guestPage.getByText(`Você entrou no workspace ${admin.workspace}.`)).toBeVisible()
  // Perfil Analista: exporta, mas não vê a auditoria nem gerencia membros.
  await expect(guestPage.getByRole('link', { name: 'Exportações' })).toBeVisible()
  await expect(guestPage.getByRole('link', { name: 'Auditoria' })).toHaveCount(0)
  await context.close()

  await page.goto('/auditoria')
  await expect(page.getByText('Convite aceito')).toBeVisible()
  await page.goto('/usuarios')
  await expect(page.getByRole('cell', { name: guest.email })).toBeVisible()
})

test('configurações, auditoria e exclusão controlada de um dataset', async ({ page }) => {
  await register(page, newUser('Gestora'))
  const datasetId = await uploadSample(page, 'vendas_1000.csv')
  await page.goto(`/datasets/${datasetId}/preview`)
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await waitForJobSuccess(page)

  await page.goto('/configuracoes')
  const ttl = page.getByLabel('Validade dos arquivos (horas)')
  await expect(ttl).toBeEnabled()
  await ttl.fill('48')
  await page.getByRole('button', { name: /Salvar configurações/ }).click()
  await expect(page.getByText('Configurações salvas.')).toBeVisible()

  await page.goto(`/datasets/${datasetId}`)
  const name = (await page.getByRole('heading', { level: 1 }).innerText()).trim()
  await page.getByRole('button', { name: 'Excluir', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('list', { name: 'O que será apagado' })).toContainText('Versões')
  const confirm = dialog.getByRole('button', { name: 'Excluir definitivamente' })
  await expect(confirm).toBeDisabled()
  await dialog.getByLabel(/para confirmar/).fill(name)
  await confirm.click()
  await expect(page).toHaveURL(/\/datasets$/)
  expect((await page.request.get(`/api/v1/datasets/${datasetId}`)).status()).toBe(404)

  await page.goto('/auditoria')
  await expect(page.getByText('Dataset excluído')).toBeVisible()
  await expect(page.getByText('Configurações alteradas')).toBeVisible()
})
