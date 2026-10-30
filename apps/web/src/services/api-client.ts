import type { ApiErrorBody } from '@/types/api'

export const API_BASE = '/api/v1'
const CSRF_COOKIE = 'df_csrf'
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(
    status: number,
    code: string,
    message: string,
    details?: unknown,
    requestId?: string | null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId ?? null
  }

  /** Erros de validação por campo vindos do FastAPI/Pydantic. */
  get fieldErrors(): Record<string, string> {
    if (!Array.isArray(this.details)) return {}
    const result: Record<string, string> = {}
    for (const item of this.details as { field?: string; message?: string }[]) {
      if (item.field && item.message) result[item.field] = item.message
    }
    return result
  }
}

export function readCookie(name: string): string | null {
  const match = document.cookie.split('; ').find((part) => part.startsWith(`${name}=`))
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null
}

let csrfRequest: Promise<string> | null = null

export async function getCsrfToken(force = false): Promise<string> {
  const existing = readCookie(CSRF_COOKIE)
  if (existing && !force) return existing
  csrfRequest ??= fetch(`${API_BASE}/auth/csrf`, { credentials: 'same-origin' })
    .then(async (response) => {
      if (!response.ok) throw await toApiError(response)
      const body = (await response.json()) as { csrf_token: string }
      return body.csrf_token
    })
    .finally(() => {
      csrfRequest = null
    })
  return csrfRequest
}

export async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorBody
    if (body?.error) {
      return new ApiError(
        response.status,
        body.error.code,
        body.error.message,
        body.error.details,
        body.request_id,
      )
    }
  } catch {
    // corpo não JSON (ex.: erro do proxy)
  }
  return new ApiError(response.status, 'http_error', mensagemPorStatus(response.status))
}

function mensagemPorStatus(status: number): string {
  if (status === 413) return 'O arquivo excede o tamanho máximo permitido.'
  if (status === 502 || status === 503 || status === 504)
    return 'Serviço temporariamente indisponível. Tente novamente.'
  return 'Erro inesperado na comunicação com o servidor.'
}

export const networkError = () =>
  new ApiError(0, 'network_error', 'Não foi possível conectar ao servidor. Verifique sua conexão.')

interface RequestOptions {
  method?: string
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

export async function api<T>(
  path: string,
  options: RequestOptions = {},
  retried = false,
): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (UNSAFE.has(method)) headers['X-CSRF-Token'] = await getCsrfToken()

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      credentials: 'same-origin',
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw networkError()
  }

  if (!response.ok) {
    const apiError = await toApiError(response)
    // Token CSRF desatualizado (ex.: após login em outra aba): renova uma única vez.
    if (apiError.code === 'csrf_failed' && !retried) {
      await getCsrfToken(true)
      return api<T>(path, options, true)
    }
    throw apiError
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Erro inesperado.'
}
