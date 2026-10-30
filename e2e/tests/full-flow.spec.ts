import { expect, test } from '@playwright/test'

import { newUser, register, uploadSample } from './helpers'

test('login → upload → preview → processamento → resultado → explorer', async ({ page }) => {
  const user = newUser('Fluxo')
  await register(page, user)

  // A sessão nunca fica acessível ao JavaScript e, em HTTPS, só trafega por conexão segura.
  const cookies = await page.context().cookies()
  const session = cookies.find((cookie) => cookie.name === 'df_session')
  expect(session?.httpOnly).toBe(true)
  expect(session?.secure).toBe(page.url().startsWith('https:'))

  // Logout e login explícitos (cobre o fluxo de autenticação com CSRF).
  await page.getByRole('button', { name: 'Menu do usuário' }).click()
  await page.getByRole('menuitem', { name: 'Sair' }).click()
  await expect(page).toHaveURL(/\/entrar/)
  await page.getByLabel('E-mail').fill(user.email)
  await page.getByLabel('Senha').fill(user.password)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.getByRole('heading', { name: /Olá/ })).toBeVisible()

  // Upload real (corpo binário em streaming até o armazenamento de objetos).
  const datasetId = await uploadSample(page, 'vendas_1000.csv')

  // Pré-visualização: colunas, tipos inferidos e primeiras linhas.
  await page.goto(`/datasets/${datasetId}/preview`)
  await expect(page.getByRole('heading', { name: 'vendas 1000' })).toBeVisible()
  await expect(page.getByText('Registros (exato)')).toBeVisible()
  await expect(page.getByLabel('Tipo da coluna valor')).toHaveText('Decimal')
  await expect(page.getByLabel('Tipo da coluna data_venda')).toHaveText('Data')
  await expect(page.getByText('Primeiras 20 linhas')).toBeVisible()

  // Configuração: renomeia uma coluna e inicia o processamento.
  await page.getByLabel('Nome da coluna valor').fill('valor_total')
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()

  // Acompanhamento real do job até a conclusão.
  await expect(page).toHaveURL(/\/processamentos\//)
  await expect(page.getByText('Concluído').first()).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('Reconciliação — versão 1')).toBeVisible()
  await expect(page.getByText('Válidos (publicados)')).toBeVisible()

  // Registros persistidos consultados no servidor (DuckDB sobre Parquet).
  await page.getByRole('link', { name: 'Ver registros' }).click()
  await expect(page.getByText('1–50 de 1.000 registros')).toBeVisible()
  await expect(page.getByRole('columnheader', { name: /valor_total/ })).toBeVisible()

  // Ordenação no servidor.
  await page.getByRole('button', { name: /valor_total/ }).click()
  await expect(page.getByRole('columnheader', { name: /valor_total/ })).toHaveAttribute('aria-sort', 'ascending')

  // Visão geral reflete dados reais; módulos futuros aparecem como "Em desenvolvimento".
  await page.goto('/')
  await expect(page.getByText('Registros publicados')).toBeVisible()
  await expect(page.getByText('1.000', { exact: true })).toBeVisible()
  await page.goto('/qualidade')
  await expect(page.getByText('Em desenvolvimento')).toBeVisible()
})

test('dataset com problemas: rejeições com motivo e valor original', async ({ page }) => {
  await register(page, newUser('Qualidade'))
  const datasetId = await uploadSample(page, 'qualidade_1000.csv')
  await page.goto(`/datasets/${datasetId}/preview`)
  await expect(page.getByText(/quantidade de campos diferente do cabeçalho/)).toBeVisible()
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await expect(page.getByText('Concluído').first()).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('Rejeições por motivo')).toBeVisible()
  await expect(page.getByText('Campos a menos').first()).toBeVisible()
  await expect(page.getByText('Registros rejeitados', { exact: true })).toBeVisible()
})
