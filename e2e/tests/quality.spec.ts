import { expect, test } from '@playwright/test'

import { newUser, register, uploadSample, waitForJobSuccess } from './helpers'

test('qualidade: nota, indicadores e inconsistências da versão processada', async ({ page }) => {
  await register(page, newUser('Qualidade'))
  const datasetId = await uploadSample(page, 'qualidade_1000.csv')
  await page.goto(`/datasets/${datasetId}/preview`)
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await waitForJobSuccess(page)

  // O worker publica o relatório junto com a versão; a tela abre a partir do dataset.
  await page.goto(`/datasets/${datasetId}`)
  await page.locator('main').getByRole('link', { name: 'Qualidade' }).click()
  await expect(page.getByRole('heading', { name: 'Qualidade dos Dados' })).toBeVisible()
  const score = page.getByTestId('quality-score')
  await expect(score).toHaveText(/^\d{1,3},\d$/)
  const value = Number((await score.innerText()).replace(',', '.'))
  expect(value).toBeGreaterThan(0)
  expect(value).toBeLessThanOrEqual(100)

  const indicators = page.getByRole('region', { name: 'Indicadores' })
  await expect(indicators.getByText('Total de registros')).toBeVisible()
  await expect(indicators.getByText('1.000', { exact: true })).toBeVisible()
  await expect(page.getByText('Completude por coluna')).toBeVisible()
  await expect(page.getByText('Erros por categoria')).toBeVisible()

  const inconsistencies = page.getByRole('region', { name: 'Inconsistências' })
  await expect(inconsistencies.getByText('Leitura e mapeamento do arquivo').first()).toBeVisible()
  await expect(inconsistencies.getByText('Linha vazia').first()).toBeVisible()
  await expect(page.getByText('Comparação entre versões')).toBeVisible()
})

test('data explorer: busca, filtros e colunas consultados no servidor', async ({ page }) => {
  await register(page, newUser('Explorer'))
  const datasetId = await uploadSample(page, 'vendas_1000.csv')
  await page.goto(`/datasets/${datasetId}/preview`)
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await waitForJobSuccess(page)

  await page.goto(`/datasets/${datasetId}/explorar`)
  await expect(page.getByText('registros na versão')).toBeVisible()

  // Busca textual: a contagem vem do servidor e só a página atual é carregada.
  const queries: { search?: string; filters: unknown[]; columns?: string[] }[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/rows/query')) queries.push(request.postDataJSON())
  })
  await page.getByLabel('Buscar nas colunas de texto').fill('Lima')
  await expect(page.getByText(/de 1\.000 registros atendem/)).toBeVisible()
  expect(queries.at(-1)?.search).toBe('Lima')

  // Filtro tipado (primeira coluna "não é nulo") aplicado junto com a busca.
  await page.getByRole('button', { name: /Filtros/ }).click()
  await page.getByRole('button', { name: 'Adicionar filtro' }).click()
  await page.getByRole('button', { name: 'Aplicar filtros' }).click()
  await expect.poll(() => queries.at(-1)?.filters.length).toBe(1)

  // Ocultar uma coluna remove-a da consulta e da tabela.
  await page.getByRole('button', { name: /Colunas/ }).click()
  await page.getByRole('checkbox', { name: 'Mostrar canal' }).click()
  await expect(page.getByRole('columnheader', { name: /canal/ })).toHaveCount(0)
  expect(queries.at(-1)?.columns).not.toContain('canal')

  await page.getByRole('button', { name: 'Limpar' }).click()
  await expect(page.getByText('registros na versão')).toBeVisible()
})
