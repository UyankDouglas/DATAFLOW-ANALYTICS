import path from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { newUser, register, SAMPLES, uploadSample } from './helpers'

/**
 * Gera as capturas do README a partir de um fluxo real com os dados fictícios de samples/.
 * Executado somente sob demanda: CAPTURE_SCREENSHOTS=1 pnpm test screenshots
 */
test.skip(!process.env.CAPTURE_SCREENSHOTS, 'captura de telas apenas sob demanda')

const OUT = path.resolve(SAMPLES, '../docs/screenshots')

async function shot(page: Page, name: string) {
  await page.waitForTimeout(900) // animações de entrada e dos gráficos
  await page.screenshot({ path: path.join(OUT, `${name}.png`) })
}

async function processSample(page: Page, file: string): Promise<string> {
  const id = await uploadSample(page, file)
  await page.goto(`/datasets/${id}/preview`)
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await expect(page.getByText('Concluído').first()).toBeVisible({ timeout: 60_000 })
  return id
}

test('capturas de tela', async ({ page }) => {
  await page.goto('/entrar')
  await shot(page, '01-login')

  await register(page, newUser('Demo'))
  const salesId = await processSample(page, 'vendas_1000.csv')
  await processSample(page, 'atendimentos_1000.csv')
  await shot(page, '05-job-concluido')

  await page.goto('/importar')
  await page.getByLabel('Selecionar arquivos CSV').setInputFiles(path.join(SAMPLES, 'qualidade_1000.csv'))
  await expect(page.getByRole('link', { name: 'Configurar e processar' }).first()).toBeVisible()
  await shot(page, '03-importar')

  await page.goto('/')
  await shot(page, '02-visao-geral')

  await page.goto('/datasets')
  const draft = page.getByRole('link', { name: 'Configurar' }).first()
  await draft.click()
  await expect(page.getByText('Mapeamento de colunas').first()).toBeVisible()
  await shot(page, '04-preview')

  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await expect(page.getByText('Concluído').first()).toBeVisible({ timeout: 60_000 })
  await page.getByText('Rejeições por motivo').scrollIntoViewIfNeeded()
  await shot(page, '06-rejeicoes')

  await page.goto(`/datasets/${salesId}/explorar`)
  await expect(page.getByText(/de 1.000 registros/)).toBeVisible()
  await shot(page, '07-explorer')

  await page.evaluate(() => localStorage.setItem('df-theme', 'light'))
  await page.goto('/processamentos')
  await expect(page.getByText('Histórico de processamento').first()).toBeVisible()
  await shot(page, '08-historico-tema-claro')
  await page.evaluate(() => localStorage.setItem('df-theme', 'dark'))
})
