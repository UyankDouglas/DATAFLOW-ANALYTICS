import { afterEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse } from '@/test/render'

import { api, ApiError } from './api-client'

afterEach(() => vi.unstubAllGlobals())

describe('cliente da API', () => {
  it('envia o token CSRF em requisições que alteram estado', async () => {
    document.cookie = 'df_csrf=token-123; path=/'
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ message: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)

    await api('/auth/logout', { method: 'POST' })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/auth/logout')
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('token-123')
    expect(init.credentials).toBe('same-origin')
  })

  it('converte o envelope de erro padronizado em ApiError com erros por campo', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: 'validation_error',
              message: 'Os dados enviados são inválidos.',
              details: [
                { field: 'password', message: 'a senha precisa ter ao menos 10 caracteres' },
              ],
            },
            request_id: 'abc',
          },
          422,
        ),
      ),
    )
    const error = await api('/datasets').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(422)
    expect((error as ApiError).fieldErrors).toEqual({
      password: 'a senha precisa ter ao menos 10 caracteres',
    })
    expect((error as ApiError).requestId).toBe('abc')
  })

  it('renova o token CSRF uma única vez quando o servidor o recusa', async () => {
    document.cookie = 'df_csrf=antigo; path=/'
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: 'csrf_failed', message: 'x', details: null }, request_id: null },
          403,
        ),
      )
      .mockResolvedValueOnce(jsonResponse({ csrf_token: 'novo' }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api('/jobs/1/cancel', { method: 'POST' })).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/auth/csrf')
  })

  it('reporta falha de rede com mensagem em português', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const error = (await api('/datasets').catch((e: unknown) => e)) as ApiError
    expect(error.code).toBe('network_error')
    expect(error.message).toMatch(/Não foi possível conectar/)
  })
})
