import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse, renderWithProviders } from '@/test/render'

import { LoginPage } from './login-page'

afterEach(() => vi.unstubAllGlobals())

describe('LoginPage', () => {
  it('valida campos antes de chamar a API', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderWithProviders(<LoginPage />, { route: '/entrar', path: '/entrar' })

    await userEvent.type(screen.getByLabelText('E-mail'), 'invalido')
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))

    expect(await screen.findByText('Informe um e-mail válido.')).toBeInTheDocument()
    expect(screen.getByText('Informe a senha.')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('exibe a mensagem de erro da API em caso de credenciais inválidas', async () => {
    document.cookie = 'df_csrf=tk; path=/'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: 'invalid_credentials',
              message: 'E-mail ou senha inválidos.',
              details: null,
            },
            request_id: null,
          },
          401,
        ),
      ),
    )
    renderWithProviders(<LoginPage />, { route: '/entrar', path: '/entrar' })

    await userEvent.type(screen.getByLabelText('E-mail'), 'ana@example.com')
    await userEvent.type(screen.getByLabelText('Senha'), 'senha-errada-123')
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))

    expect(await screen.findByText('E-mail ou senha inválidos.')).toBeInTheDocument()
  })

  it('redireciona após login bem-sucedido', async () => {
    document.cookie = 'df_csrf=tk; path=/'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          user: {
            id: '1',
            email: 'ana@example.com',
            full_name: 'Ana',
            created_at: '2025-01-01T00:00:00Z',
          },
          workspace: { id: 'w', name: 'WS', slug: 'ws', role: 'admin' },
          permissions: [],
          csrf_token: 'tk2',
        }),
      ),
    )
    renderWithProviders(<LoginPage />, { route: '/entrar', path: '/entrar' })
    await userEvent.type(screen.getByLabelText('E-mail'), 'ana@example.com')
    await userEvent.type(screen.getByLabelText('Senha'), 'Senha-forte-123')
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    await waitFor(() => expect(screen.getByText('outra rota')).toBeInTheDocument())
  })
})
