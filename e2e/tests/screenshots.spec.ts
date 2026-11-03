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
  await page.getByText('Exclusões por motivo').scrollIntoViewIfNeeded()
  await shot(page, '06-rejeicoes')

  await page.goto(`/datasets/${salesId}/explorar`)
  await expect(page.getByText(/de 1.000 registros/)).toBeVisible()
  await shot(page, '07-explorer')

  // Fase 2: prévia de planilha (aba, cabeçalho abaixo do título) e tela de transformações.
  const workbookId = await uploadSample(page, 'vendas_atendimentos_1000.xlsx')
  await page.goto(`/datasets/${workbookId}/preview`)
  await expect(page.getByText('Leitura da planilha')).toBeVisible()
  await shot(page, '10-preview-xlsx')

  // Largura em que regras e prévia ficam lado a lado.
  await page.setViewportSize({ width: 1720, height: 1000 })
  await page.goto(`/transformacoes?dataset=${salesId}`)
  await page.getByLabel('Nome do conjunto').fill('Limpeza de vendas')
  for (const operation of ['Remover espaços excedentes', 'Filtrar registros', 'Remover duplicidades']) {
    await page.getByRole('combobox', { name: 'Adicionar regra' }).click()
    await page.getByRole('option', { name: operation }).click()
  }
  const dedup = page.getByRole('listitem', { name: /Remover duplicidades/ })
  await dedup.getByRole('checkbox', { name: 'vendedor' }).check()
  await dedup.getByRole('checkbox', { name: 'produto' }).check()
  await page.getByRole('button', { name: 'Gerar prévia' }).click()
  await expect(page.getByRole('region', { name: 'Prévia' }).getByText(/Recebidos = válidos/)).toBeVisible()
  await page
    .getByText('Regras', { exact: true })
    .first()
    .evaluate((element) => element.scrollIntoView({ block: 'start' }))
  await shot(page, '09-transformacoes')
  await page.setViewportSize({ width: 1440, height: 900 })

  await page.evaluate(() => localStorage.setItem('df-theme', 'light'))
  await page.goto('/processamentos')
  await expect(page.getByText('Histórico de processamento').first()).toBeVisible()
  await shot(page, '08-historico-tema-claro')
  await page.evaluate(() => localStorage.setItem('df-theme', 'dark'))
})
