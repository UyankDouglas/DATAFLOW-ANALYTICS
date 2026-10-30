import fs from 'node:fs'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { newUser, register, SAMPLES } from './helpers'

const LARGE_FILE = path.join(SAMPLES, 'generated', 'vendas_100000.csv')
const ROWS = 100_000
const TWO_MB = 2 * 1024 * 1024

test('100 mil linhas pela interface: upload acima de 2 MB, processamento e consulta', async ({
  page,
}, testInfo) => {
  // Na CI o arquivo é obrigatório: se faltar, o teste falha em vez de ser ignorado.
  test.skip(
    !process.env.CI && !fs.existsSync(LARGE_FILE),
    'gere com: python scripts/generate_samples.py --rows 100000 --only vendas',
  )
  test.setTimeout(240_000)
  const fileBytes = fs.statSync(LARGE_FILE).size
  expect(fileBytes, 'o arquivo precisa exceder o limite geral do proxy').toBeGreaterThan(TWO_MB)

  await register(page, newUser('Volume'))

  // Upload pela interface: mede do envio até o arquivo estar armazenado.
  await page.goto('/importar')
  const uploadStart = Date.now()
  await page.getByLabel('Selecionar arquivos CSV').setInputFiles(LARGE_FILE)
  const configure = page.getByRole('link', { name: 'Configurar e processar' }).first()
  await expect(configure).toBeVisible({ timeout: 120_000 })
  const uploadMs = Date.now() - uploadStart

  // Arquivo maior que a amostra da pré-visualização: a contagem é informada como estimada.
  await configure.click()
  await expect(page.getByText('Registros (estimado)')).toBeVisible()
  await expect(page.getByLabel('Tipo da coluna valor')).toHaveText('Decimal')

  const jobStart = Date.now()
  await page.getByRole('button', { name: 'Iniciar processamento' }).last().click()
  await expect(page).toHaveURL(/\/processamentos\//)
  await expect(page.getByText('Reconciliação — versão 1')).toBeVisible({ timeout: 180_000 })
  const jobMs = Date.now() - jobStart

  // Contagens e progresso conferidos no estado durável do job.
  const jobId = new URL(page.url()).pathname.split('/').pop()
  const job = await (await page.request.get(`/api/v1/jobs/${jobId}`)).json()
  expect(job.status).toBe('succeeded')
  expect(job.rows_total).toBe(ROWS)
  expect(job.rows_valid).toBe(ROWS)
  expect(job.rows_rejected).toBe(0)
  expect(job.bytes_processed).toBe(fileBytes)
  expect(job.progress_percent).toBe(100)

  // Consulta no fim do dataset: a primeira baixa o Parquet para o cache, a segunda já o encontra.
  const rowsUrl = `/api/v1/datasets/${job.dataset_id}/rows?page=2000&page_size=50&sort=valor&direction=desc`
  const coldStart = Date.now()
  const cold = await page.request.get(rowsUrl)
  const coldQueryMs = Date.now() - coldStart
  expect(cold.status()).toBe(200)
  const warmStart = Date.now()
  const warm = await page.request.get(rowsUrl)
  const warmQueryMs = Date.now() - warmStart
  const body = await warm.json()
  expect(body.total).toBe(ROWS)
  expect(body.rows).toHaveLength(50)

  // Decimais ordenados por valor, não como texto, e trafegando como texto.
  const valueIndex = body.columns.findIndex((column: { name: string }) => column.name === 'valor')
  const values: string[] = body.rows.map((row: unknown[]) => row[valueIndex])
  expect(values.every((value) => typeof value === 'string')).toBe(true)
  const numbers = values.map(Number)
  expect(numbers).toEqual([...numbers].sort((a, b) => b - a))

  await page.goto(`/datasets/${job.dataset_id}/explorar`)
  await expect(page.getByText('1–50 de 100.000 registros')).toBeVisible()

  // Medições reais desta execução: registradas no log da CI para o docs/benchmark.md.
  const measurements = {
    file_bytes: fileBytes,
    upload_wall_ms: uploadMs,
    job_wall_ms: jobMs,
    query_cold_ms: coldQueryMs,
    query_warm_ms: warmQueryMs,
    metrics: job.metrics,
  }
  console.log(`BENCHMARK_E2E ${JSON.stringify(measurements)}`)
  await testInfo.attach('medicoes.json', {
    body: JSON.stringify(measurements, null, 2),
    contentType: 'application/json',
  })
})

test('o proxy recusa corpos acima de 2 MB fora da rota de upload', async ({ request, baseURL }) => {
  test.skip(
    Boolean(baseURL?.includes(':5173')),
    'o limite é aplicado pelo Caddy; o servidor de desenvolvimento não o usa',
  )
  const { csrf_token: csrfToken } = await (await request.get('/api/v1/auth/csrf')).json()
  const response = await request.post('/api/v1/auth/login', {
    headers: { 'X-CSRF-Token': csrfToken, 'Content-Type': 'application/json' },
    data: JSON.stringify({ email: 'limite@example.com', password: 'x'.repeat(3 * 1024 * 1024) }),
  })
  // Sem o limite do proxy, a API leria o corpo inteiro e responderia 422.
  expect([413, 502], `status recebido: ${response.status()}`).toContain(response.status())
})
