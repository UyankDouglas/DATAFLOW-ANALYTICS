import { expect, test } from '@playwright/test'

import { newUser, register, uploadSample } from './helpers'

test('usuário de outro workspace não acessa dataset, arquivo nem registros alheios', async ({ browser }) => {
  const ownerContext = await browser.newContext()
  const owner = await ownerContext.newPage()
  await register(owner, newUser('Dono'))
  const datasetId = await uploadSample(owner, 'vendas_1000.csv')
  await owner.goto(`/datasets/${datasetId}/preview`)
  await owner.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await expect(owner.getByText('Concluído').first()).toBeVisible({ timeout: 60_000 })
  const jobUrl = owner.url()

  const intruderContext = await browser.newContext()
  const intruder = await intruderContext.newPage()
  await register(intruder, newUser('Intruso'))

  // Pela interface: telas por ID retornam "não encontrado".
  await intruder.goto(`/datasets/${datasetId}`)
  await expect(intruder.getByText('Dataset não encontrado.')).toBeVisible()
  await intruder.goto(`/datasets/${datasetId}/preview`)
  await expect(intruder.getByText('Dataset não encontrado.')).toBeVisible()
  await intruder.goto(new URL(jobUrl).pathname)
  await expect(intruder.getByText('Processamento não encontrado.')).toBeVisible()

  // Pela API, com a sessão do intruso: conteúdo do arquivo e registros não vazam.
  for (const path of [
    `/api/v1/datasets/${datasetId}`,
    `/api/v1/datasets/${datasetId}/preview`,
    `/api/v1/datasets/${datasetId}/rows`,
    `/api/v1/datasets/${datasetId}/versions`,
  ]) {
    const response = await intruder.request.get(path)
    expect(response.status(), path).toBe(404)
  }
  const list = await intruder.request.get('/api/v1/datasets')
  expect((await list.json()).total).toBe(0)

  await ownerContext.close()
  await intruderContext.close()
})
