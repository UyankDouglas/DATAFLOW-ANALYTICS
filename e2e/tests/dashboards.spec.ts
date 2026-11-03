import { expect, test, type Page } from '@playwright/test'

import { newUser, register, uploadSample } from './helpers'

// samples/vendas_1000.csv é fixo: soma de "valor" 4.340.899,35; só as vendas pagas, 3.236.897,89.
const TOTAL = '4.340.899,35'
const PAID = '3.236.897,89'

async function processedSales(page: Page): Promise<string> {
  const datasetId = await uploadSample(page, 'vendas_1000.csv')
  await page.goto(`/datasets/${datasetId}/preview`)
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await expect(page.getByText('Concluído').first()).toBeVisible({ timeout: 60_000 })
  return datasetId
}

async function choose(page: Page, label: string, option: string | RegExp) {
  await page.getByRole('combobox', { name: label }).click()
  await page.getByRole('option', { name: option }).click()
}

test('dashboard geral: KPIs, gráficos e comparação calculados pela API', async ({ page }) => {
  await register(page, newUser('Analise'))
  const datasetId = await processedSales(page)
  await page.goto(`/dashboards/geral?dataset=${datasetId}&medida=valor&categoria=equipe`)

  const indicators = page.getByRole('region', { name: 'Indicadores' })
  await expect(indicators.getByText('1.000', { exact: true })).toBeVisible()
  await expect(indicators.getByText(TOTAL)).toBeVisible()
  await expect(indicators.getByText('equipe distintos')).toBeVisible()
  await expect(page.getByRole('region', { name: /Evolução temporal/ })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Tabela analítica por equipe' }).getByRole('table')).toBeVisible()
  // Comparação: período sugerido a partir da data mais recente dos dados.
  const comparison = page.getByRole('region', { name: 'Soma de valor no período' })
  await expect(comparison.getByTestId('kpi-variation')).toHaveText(/^[+-]?\d/)
})

test('construtor: cria, filtra, reabre e reorganiza um dashboard', async ({ page }) => {
  await register(page, newUser('Dashboard'))
  await processedSales(page)

  await page.goto('/dashboards/construtor')
  await page.getByLabel('Nome', { exact: true }).fill('Vendas por equipe')
  await choose(page, 'Dataset', /vendas/)

  await page.getByRole('button', { name: 'Card KPI' }).click()
  const editor = page.getByRole('dialog')
  await editor.getByRole('textbox', { name: 'Título' }).fill('Valor total')
  await choose(page, 'Coluna da medida 1', 'valor · Decimal')
  await expect(editor.getByTestId('kpi-value')).toHaveText(TOTAL) // prévia calculada pela API
  await editor.getByRole('button', { name: 'Salvar widget' }).click()

  await page.getByRole('button', { name: 'Barras', exact: true }).click()
  await editor.getByRole('textbox', { name: 'Título' }).fill('Registros por equipe')
  await choose(page, 'Agrupar por', 'equipe · Texto')
  await editor.getByRole('button', { name: 'Salvar widget' }).click()

  await page.getByRole('button', { name: 'Salvar dashboard' }).click()
  await expect(page).toHaveURL(/\/dashboards\/[0-9a-f-]{36}$/)
  const kpi = page.getByRole('region', { name: 'Valor total' })
  await expect(kpi.getByTestId('kpi-value')).toHaveText(TOTAL)
  await expect(page.getByRole('region', { name: 'Registros por equipe' }).getByText(/1\.000 registros/)).toBeVisible()

  // Filtro interativo da tela: só vendas pagas, aplicado no servidor a cada widget.
  const queries: { extra_filters: unknown[] }[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/query')) queries.push(request.postDataJSON())
  })
  await page.getByRole('button', { name: 'Filtrar por valores' }).click()
  await choose(page, 'Coluna 1', 'status')
  await page.getByRole('checkbox', { name: 'pago' }).check()
  await page.getByRole('button', { name: 'Aplicar filtros' }).click()
  await expect(kpi.getByTestId('kpi-value')).toHaveText(PAID)
  expect(queries.at(-1)?.extra_filters).toEqual([
    { match: 'all', filters: [{ column: 'status', operator: 'in', values: ['pago'] }] },
  ])

  // Reabrir: a configuração vem do banco e os números, de novo, da API.
  await page.reload()
  await expect(page.getByRole('region', { name: 'Valor total' }).getByTestId('kpi-value')).toHaveText(TOTAL)

  // Reorganizar e salvar: a nova ordem persiste.
  await page.getByRole('link', { name: 'Editar' }).click()
  await page.getByRole('button', { name: 'Mover Registros por equipe para antes' }).click()
  await page.getByRole('button', { name: 'Salvar dashboard' }).click()
  await expect(page.getByText('Dashboard salvo.')).toBeVisible()
  await expect(page.locator('main [role="region"]')).toHaveCount(2)
  const order = await page
    .locator('main [role="region"]')
    .evaluateAll((elements) => elements.map((e) => e.getAttribute('aria-label')))
  expect(order).toEqual(['Registros por equipe', 'Valor total'])

  await page.goto('/dashboards')
  await expect(page.getByRole('link', { name: 'Vendas por equipe' })).toBeVisible()
  await expect(page.getByText('2 widgets')).toBeVisible()
})
