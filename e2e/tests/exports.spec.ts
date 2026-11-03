import { expect, test, type Page } from '@playwright/test'

import { newUser, register, uploadSample } from './helpers'

async function processedSales(page: Page): Promise<string> {
  const datasetId = await uploadSample(page, 'vendas_1000.csv')
  await page.goto(`/datasets/${datasetId}/preview`)
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await expect(page.getByText('Concluído').first()).toBeVisible({ timeout: 60_000 })
  return datasetId
}

/** Espera a exportação mais recente ficar pronta e devolve o endereço de download. */
async function readyDownload(page: Page): Promise<string> {
  await page.goto('/exportacoes')
  const download = page.getByRole('link', { name: /Baixar/ }).first()
  await expect(download).toBeVisible({ timeout: 60_000 }) // a lista se atualiza sozinha
  const href = await download.getAttribute('href')
  expect(href).toMatch(/^\/api\/v1\/exports\/[0-9a-f-]{36}\/download$/)
  return href ?? ''
}

test('exportação dos registros filtrados no explorer, baixada só pela API', async ({
  page,
  browser,
}) => {
  await register(page, newUser('Exporta'))
  const datasetId = await processedSales(page)
  await page.goto(`/datasets/${datasetId}/explorar`)
  await page.getByLabel('Buscar nas colunas de texto').fill('Lima')
  await expect(page.getByText(/de 1\.000 registros atendem/)).toBeVisible()
  // A contagem filtrada chega depois do texto (busca com debounce): espera sair de 1.000.
  const count = page.locator('p[aria-live="polite"] strong')
  await expect(count).not.toHaveText('1.000')
  const matched = Number((await count.innerText()).replace(/\./g, ''))
  expect(matched).toBeGreaterThan(0)

  await page.getByRole('button', { name: 'Exportar' }).click()
  await page.getByRole('menuitem', { name: /CSV para Excel em português/ }).click()
  await expect(
    page.getByText(`Exportação de ${matched.toLocaleString('pt-BR')} registros na fila.`),
  ).toBeVisible()

  const href = await readyDownload(page)
  const response = await page.request.get(href)
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toBe('text/csv; charset=utf-8')
  expect(response.headers()['cache-control']).toBe('no-store')
  const lines = (await response.text()).replace(/^\uFEFF/, '').trim().split(/\r?\n/)
  expect(lines[0]).toBe('data_venda;vendedor;equipe;produto;categoria;quantidade;valor;status;canal')
  expect(lines).toHaveLength(matched + 1)
  expect(lines.slice(1).every((line) => line.toLowerCase().includes('lima'))).toBe(true)

  // Outro workspace não baixa o arquivo, mesmo com o endereço.
  const other = await browser.newContext()
  const intruder = await other.newPage()
  await register(intruder, newUser('Intrusa'))
  expect((await intruder.request.get(href)).status()).toBe(404)
  await other.close()
})

test('relatório agrupado exportado em XLSX', async ({ page }) => {
  await register(page, newUser('Relatorio'))
  const datasetId = await processedSales(page)
  await page.goto(`/relatorios?dataset=${datasetId}`)
  await page.getByRole('combobox', { name: 'Agrupar por' }).click()
  await page.getByRole('option', { name: 'equipe', exact: true }).click()
  const report = page.getByRole('region', { name: 'Relatório' })
  await expect(report.getByRole('row')).toHaveCount(6) // cabeçalho + 5 equipes
  await expect(page.getByText('1.000 registros considerados')).toBeVisible()

  await page.getByRole('button', { name: 'Exportar relatório' }).click()
  await page.getByRole('menuitem', { name: /Planilha XLSX/ }).click()
  await expect(page.getByText('Exportação do relatório na fila.')).toBeVisible()
  const response = await page.request.get(await readyDownload(page))
  expect(response.headers()['content-type']).toBe(
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  )
  expect(response.headers()['content-disposition']).toMatch(/_relatorio_\d{8}-\d{4}\.xlsx"$/)
  const body = await response.body()
  expect(body.subarray(0, 2).toString()).toBe('PK') // arquivo ZIP (XLSX) íntegro
})
