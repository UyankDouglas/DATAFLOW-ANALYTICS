import { expect, test, type Locator, type Page } from '@playwright/test'

import { newUser, register, uploadSample, waitForJobSuccess } from './helpers'

const XLSX = 'vendas_atendimentos_1000.xlsx'

/** Número exibido logo depois de um rótulo (cartões de contagem e reconciliação). */
async function countAfter(scope: Locator, label: string): Promise<number> {
  const value = scope.getByText(label, { exact: true }).locator('xpath=following-sibling::*[1]')
  return Number((await value.innerText()).replace(/\D/g, ''))
}

async function processCurrentPreview(page: Page) {
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await waitForJobSuccess(page)
}

test('XLSX: aba, linha do cabeçalho, obrigatoriedade e fórmulas nunca executadas', async ({ page }) => {
  await register(page, newUser('Planilha'))
  const datasetId = await uploadSample(page, XLSX)

  // A detecção pula o título acima da tabela da aba "Vendas" (cabeçalho na linha 3).
  await page.goto(`/datasets/${datasetId}/preview`)
  await expect(page.getByText('Leitura da planilha')).toBeVisible()
  await expect(page.getByLabel('Linha do cabeçalho')).toHaveValue('3')
  await expect(page.getByText('Intervalo A3:I1003 · 3 aba(s)')).toBeVisible()
  await expect(page.getByText('Registros (exato)')).toBeVisible()
  await expect(page.getByLabel('Tipo da coluna data_venda')).toHaveText('Data')
  await expect(page.getByLabel('Tipo da coluna valor')).toHaveText('Decimal')

  await page.getByLabel('Coluna vendedor obrigatória').check()
  await page.getByLabel('Valor para vazios da coluna canal').fill('não informado')
  await processCurrentPreview(page)
  await expect(page.getByText('Importação', { exact: true })).toBeVisible()
  await expect(page.getByText('aba Vendas')).toBeVisible()
  await expect(page.getByText('Reconciliação — versão 1')).toBeVisible()

  // A aba de totais tem fórmulas sem valor salvo: viram rejeição explícita, nunca cálculo.
  await page.goto(`/datasets/${datasetId}/preview`)
  await page.getByRole('button', { name: 'Importar a aba Totais como novo dataset' }).click()
  await expect(page.getByRole('heading', { name: /Totais$/ })).toBeVisible()
  await expect(page.getByText(/Fórmulas não são executadas/)).toBeVisible()
  await processCurrentPreview(page)
  await expect(page.getByText('Fórmula sem valor salvo').first()).toBeVisible()
  await expect(page.getByText('Registros excluídos', { exact: true })).toBeVisible()
})

test('transformações: prévia, duplicidades e nova versão com linhagem', async ({ page }) => {
  await register(page, newUser('Regras'))
  const datasetId = await uploadSample(page, 'qualidade_1000.csv')
  await page.goto(`/datasets/${datasetId}/preview`)
  await processCurrentPreview(page)

  await page.goto(`/datasets/${datasetId}`)
  await page.getByRole('link', { name: 'Transformar' }).click()
  await expect(page.getByRole('heading', { name: 'Transformações' })).toBeVisible()

  await page.getByLabel('Nome do conjunto').fill('Limpeza e duplicidades')
  for (const operation of ['Remover espaços excedentes', 'Remover duplicidades']) {
    await page.getByRole('combobox', { name: 'Adicionar regra' }).click()
    await page.getByRole('option', { name: operation }).click()
  }
  const dedup = page.getByRole('listitem', { name: /Regra 2: Remover duplicidades/ })
  await dedup.getByRole('checkbox', { name: 'vendedor' }).check()
  await dedup.getByRole('checkbox', { name: 'produto' }).check()
  await expect(dedup.getByText('Resumo: chave: vendedor, produto · manter o primeiro')).toBeVisible()

  // Prévia sobre amostra: a reconciliação fecha antes de gravar qualquer coisa.
  await page.getByRole('button', { name: 'Gerar prévia' }).click()
  const preview = page.getByRole('region', { name: 'Prévia' })
  await expect(preview.getByText(/Recebidos = válidos \+ rejeitados \+ filtrados \+ duplicados/)).toBeVisible()

  // Análise da versão inteira com a mesma chave (antes do trim, só duplicidades exatas).
  const analysis = page.getByRole('region', { name: 'Duplicidades na versão inteira' })
  await analysis.getByRole('checkbox', { name: 'vendedor' }).check()
  await analysis.getByRole('checkbox', { name: 'produto' }).check()
  await analysis.getByRole('button', { name: 'Analisar duplicidades' }).click()
  await expect(analysis.getByText('Registros duplicados')).toBeVisible()
  const analyzed = await countAfter(analysis, 'Registros duplicados')
  expect(analyzed).toBeGreaterThan(0)

  await page.getByRole('button', { name: 'Salvar conjunto' }).click()
  await expect(page.getByText(/salvo \(revisão 1\)/)).toBeVisible()
  await page.getByRole('button', { name: 'Aplicar e gerar nova versão' }).click()

  await waitForJobSuccess(page)
  await expect(page.getByText('Transformação', { exact: true })).toBeVisible()
  await expect(page.getByText('Reconciliação — versão 2')).toBeVisible()
  await expect(page.getByText('Regras aplicadas')).toBeVisible()
  // Depois do trim, " Ana " e "Ana" viram a mesma chave: nunca menos duplicados que na análise.
  const removed = await countAfter(page.locator('main'), 'Duplicados (removidos)')
  expect(removed).toBeGreaterThanOrEqual(analyzed)
  await expect(page.getByText('Duplicado', { exact: true }).first()).toBeVisible()

  await page.goto(`/datasets/${datasetId}`)
  await expect(page.getByText('v1 + Limpeza e duplicidades')).toBeVisible()
})

test('planilhas inválidas ou perigosas são recusadas com motivo', async ({ page }) => {
  await register(page, newUser('Malicioso'))
  await page.goto('/importar')
  const input = page.getByLabel('Selecionar arquivos CSV ou XLSX')

  // Cabeçalho OLE com o fluxo EncryptionInfo, como o Excel grava planilhas com senha.
  const ole = Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1])
  const encrypted = Buffer.concat([
    ole,
    Buffer.alloc(504),
    Buffer.from('EncryptionInfo', 'utf16le'),
    Buffer.alloc(1024),
  ])
  await input.setInputFiles({ name: 'protegida.xlsx', mimeType: 'application/octet-stream', buffer: encrypted })
  await expect(page.getByText(/protegida por senha/)).toBeVisible()

  await input.setInputFiles({
    name: 'corrompida.xlsx',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('isto não é uma planilha'),
  })
  await expect(page.getByText('O arquivo não é uma planilha XLSX válida.')).toBeVisible()

  // Recusa no navegador, antes de qualquer envio.
  await input.setInputFiles({ name: 'macros.xlsm', mimeType: 'application/octet-stream', buffer: Buffer.from('x') })
  await expect(page.getByText(/macros não são aceitas/)).toBeVisible()

  // Nada disso virou dataset.
  const list = await page.request.get('/api/v1/datasets')
  expect((await list.json()).total).toBe(0)
})
