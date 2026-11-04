import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, type Page } from '@playwright/test'

export const SAMPLES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../samples')

export interface TestUser {
  name: string
  email: string
  password: string
  workspace: string
}

export function newUser(prefix: string): TestUser {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  return {
    name: `${prefix} Teste`,
    email: `${prefix.toLowerCase()}-${id}@example.com`,
    // Senha gerada apenas para esta execução de teste.
    password: `E2e-${id}-Senha`,
    workspace: `Workspace ${prefix} ${id.slice(-4)}`,
  }
}

export async function register(page: Page, user: TestUser): Promise<void> {
  await page.goto('/cadastro')
  await submitRegistration(page, user)
  await expect(page.getByRole('heading', { name: /Olá/ })).toBeVisible()
}

/** Preenche e envia o cadastro já aberto (o destino depois depende de onde a pessoa veio). */
export async function submitRegistration(page: Page, user: TestUser): Promise<void> {
  await page.getByLabel('Nome completo').fill(user.name)
  await page.getByLabel('E-mail').fill(user.email)
  await page.getByLabel('Nome do workspace').fill(user.workspace)
  await page.getByLabel('Senha', { exact: true }).fill(user.password)
  await page.getByLabel('Confirmar senha').fill(user.password)
  await page.getByRole('button', { name: 'Criar conta' }).click()
}

/**
 * Espera o job aberto em /processamentos/<id> terminar com sucesso.
 *
 * Não espere por `getByText('Concluído')`: as etapas do job mostram "Concluído" como rótulo da
 * última etapa desde o início, então o texto aparece antes de o worker pegar o job. Quem
 * navegava logo em seguida abria a página seguinte com o dataset ainda em processamento.
 * A reconciliação só aparece com o job concluído, e o worker publica a versão, marca o dataset
 * como pronto e conclui o job na mesma transação.
 */
export async function waitForJobSuccess(page: Page, timeout = 60_000): Promise<void> {
  await expect(page).toHaveURL(/\/processamentos\/[0-9a-f-]{36}$/)
  await expect(page.getByText(/^Reconciliação — versão \d+$/)).toBeVisible({ timeout })
}

export async function uploadSample(page: Page, file: string): Promise<string> {
  await page.goto('/importar')
  await page.getByLabel('Selecionar arquivos CSV').setInputFiles(path.join(SAMPLES, file))
  const configure = page.getByRole('link', { name: 'Configurar e processar' }).first()
  await expect(configure).toBeVisible()
  const href = await configure.getAttribute('href')
  const match = /\/datasets\/([0-9a-f-]+)\/preview/.exec(href ?? '')
  if (!match?.[1]) throw new Error(`link inesperado: ${href}`)
  return match[1]
}
