import type { UploadResponse } from '@/types/api'

import { API_BASE, ApiError, getCsrfToken, networkError } from './api-client'

export interface UploadHandle {
  promise: Promise<UploadResponse>
  abort: () => void
}

/**
 * Envia o arquivo como corpo binário (streaming no servidor). Usa XMLHttpRequest porque o
 * fetch não expõe progresso de envio; o percentual reflete bytes realmente transmitidos.
 */
export function uploadDataset(
  file: File,
  onProgress: (loaded: number, total: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest()
  const promise = getCsrfToken().then(
    (csrf) =>
      new Promise<UploadResponse>((resolve, reject) => {
        xhr.open('POST', `${API_BASE}/datasets/upload`)
        xhr.withCredentials = true
        xhr.setRequestHeader('Content-Type', 'application/octet-stream')
        xhr.setRequestHeader('X-File-Name', encodeURIComponent(file.name))
        xhr.setRequestHeader('X-CSRF-Token', csrf)
        xhr.setRequestHeader('Accept', 'application/json')
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) onProgress(event.loaded, event.total)
        }
        xhr.onload = () => {
          const body = parseJson(xhr.responseText)
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(body as UploadResponse)
            return
          }
          const error = (
            body as { error?: { code: string; message: string; details: unknown } } | null
          )?.error
          reject(
            new ApiError(
              xhr.status,
              error?.code ?? 'http_error',
              error?.message ??
                (xhr.status === 413
                  ? 'O arquivo excede o tamanho máximo permitido.'
                  : 'Falha no envio do arquivo.'),
              error?.details,
            ),
          )
        }
        xhr.onerror = () => reject(networkError())
        xhr.onabort = () => reject(new ApiError(0, 'aborted', 'Envio cancelado.'))
        xhr.send(file)
      }),
  )
  return { promise, abort: () => xhr.abort() }
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}
