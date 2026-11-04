import { expect, test, type Page } from '@playwright/test'

import { newUser, register, uploadSample } from './helpers'

async function chooseType(page: Page, column: string, type: string) {
  await page.getByLabel(`Tipo da coluna ${column}`).click()
  await page.getByRole('option', { name: type, exact: true }).click()
  await expect(page.getByLabel(`Tipo da coluna ${column}`)).toHaveText(type)
}

/**
 * A jornada do prompt mestre com um só dataset, conferindo que o mesmo número de registros
 * válidos aparece em cada etapa: processamento, qualidade, dashboard e arquivo exportado.
 */
test('jornada: login → upload → preview → configuração → processamento → qualidade → dashboard → exportação', async ({
  page,
}) => {
  const user = newUser('Jornada')
  await register(page, user)
  await page.getByRole('button', { name: 'Menu do usuário' }).click()
  await page.getByRole('menuitem', { name: 'Sair' }).click()
  await expect(page).toHaveURL(/\/entrar/)
  await page.getByLabel('E-mail').fill(user.email)
  await page.getByLabel('Senha').fill(user.password)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.getByRole('heading', { name: /Olá/ })).toBeVisible()

  // Upload e pré-visualização do arquivo com problemas propositais.
  const datasetId = await uploadSample(page, 'qualidade_1000.csv')
  await page.goto(`/datasets/${datasetId}/preview`)
  await expect(page.getByText('Primeiras 20 linhas')).toBeVisible()

  // Configuração: tipos escolhidos pela pessoa, que o worker aplica e valida registro a registro.
  await chooseType(page, 'data_venda', 'Data')
  await chooseType(page, 'quantidade', 'Inteiro')
  await chooseType(page, 'valor', 'Decimal')
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()

  // Processamento acompanhado até o fim; os números vêm do job persistido.
  await expect(page).toHaveURL(/\/processamentos\/[0-9a-f-]{36}$/)
  const jobId = page.url().split('/').at(-1) ?? ''
  const readJob = async () => (await page.request.get(`/api/v1/jobs/${jobId}`)).json()
  await expect.poll(async () => (await readJob()).status, { timeout: 60_000 }).toBe('succeeded')
  await expect(page.getByText('Reconciliação — versão 1')).toBeVisible()
  const job = await readJob()
  const valid: number = job.rows_valid
  expect(job.rows_total).toBe(job.rows_valid + job.rows_rejected)
  expect(job.rows_rejected).toBeGreaterThan(0) // datas e valores inválidos viram rejeições
  expect(valid).toBeGreaterThan(0)
  const validText = valid.toLocaleString('pt-BR')
  await expect(page.getByText('Exclusões por motivo')).toBeVisible()

  // Qualidade da versão publicada: nota abaixo de 100 e o mesmo total de válidos.
  await page.goto(`/qualidade?dataset=${datasetId}`)
  const score = Number((await page.getByTestId('quality-score').innerText()).replace(',', '.'))
  expect(score).toBeGreaterThan(0)
  expect(score).toBeLessThan(100)
  const quality = page.getByRole('region', { name: 'Indicadores' })
  await expect(quality.getByText('Registros válidos')).toBeVisible()
  await expect(quality.getByText(validText, { exact: true }).first()).toBeVisible()

  // Dashboard: indicadores calculados pela API sobre a mesma versão.
  await page.goto(`/dashboards/geral?dataset=${datasetId}&medida=valor&categoria=equipe`)
  const indicators = page.getByRole('region', { name: 'Indicadores' })
  await expect(indicators.getByText(validText, { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('region', { name: 'Tabela analítica por equipe' }).getByRole('table')).toBeVisible()

  // Exportação de todos os registros tratados, baixada pela API.
  await page.goto(`/datasets/${datasetId}/explorar`)
  await expect(page.getByText('registros na versão')).toBeVisible()
  await expect(page.locator('p[aria-live="polite"] strong')).toHaveText(validText)
  await page.getByRole('button', { name: 'Exportar' }).click()
  await page.getByRole('menuitem', { name: /CSV para Excel em português/ }).click()
  await expect(page.getByText(`Exportação de ${validText} registros na fila.`)).toBeVisible()
  await page.goto('/exportacoes')
  const download = page.getByRole('link', { name: /Baixar/ }).first()
  await expect(download).toBeVisible({ timeout: 60_000 })
  const response = await page.request.get((await download.getAttribute('href')) ?? '')
  expect(response.status()).toBe(200)
  const lines = (await response.text()).replace(/^﻿/, '').trim().split(/\r?\n/)
  expect(lines[0]).toBe('data_venda;vendedor;equipe;produto;categoria;quantidade;valor;status;canal')
  expect(lines).toHaveLength(valid + 1)
  // Nenhuma célula sai como fórmula: texto iniciado por = + - @ recebe apóstrofo.
  expect(lines.slice(1).some((line) => /(^|;)[=+@]/.test(line))).toBe(false)
})
