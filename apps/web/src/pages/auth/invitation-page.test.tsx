import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { bodiesOf, mockApi } from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'

import { InvitationPage } from './invitation-page'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
afterEach(() => vi.unstubAllGlobals())

const preview = {
  workspace_name: 'Comercial',
  role: 'analyst',
  email: 'a@example.com',
  expires_at: '2026-11-10T12:00:00Z',
}
const route = { route: '/convite?token=token-de-teste-1234567890', path: '/convite' }

describe('InvitationPage', () => {
  it('sem sessão, oferece entrar ou criar a conta e voltar ao convite', async () => {
    mockApi([], {
      'GET /auth/me': () =>
        jsonResponse({ error: { code: 'unauthenticated', message: 'x', details: null } }, 401),
      'POST /invitations/preview': () => jsonResponse(preview),
    })
    renderWithProviders(<InvitationPage />, route)
    expect(await screen.findByText('Comercial')).toBeInTheDocument()
    expect(screen.getByText('Analista')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Entrar' })).toHaveAttribute('href', '/entrar')
    expect(screen.getByRole('link', { name: 'Criar conta' })).toHaveAttribute('href', '/cadastro')
  })

  it('com a conta convidada, aceita pelo token', async () => {
    const fetchMock = mockApi([], {
      'POST /invitations/preview': () => jsonResponse(preview),
      'POST /invitations/accept': () => jsonResponse({ message: 'Convite aceito.' }),
    })
    renderWithProviders(<InvitationPage />, route)
    await userEvent.click(await screen.findByRole('button', { name: /Aceitar convite/ }))
    await waitFor(() =>
      expect(bodiesOf(fetchMock, 'POST /invitations/accept')).toEqual([
        { token: 'token-de-teste-1234567890' },
      ]),
    )
    expect(await screen.findByText('outra rota')).toBeInTheDocument() // foi para o início
  })

  it('mostra quando o convite expirou', async () => {
    mockApi([], {
      'POST /invitations/preview': () =>
        jsonResponse(
          {
            error: {
              code: 'invitation_expired',
              message: 'Este convite expirou. Peça um novo ao administrador.',
              details: null,
            },
          },
          410,
        ),
    })
    renderWithProviders(<InvitationPage />, route)
    expect(await screen.findByText(/Este convite expirou/)).toBeInTheDocument()
  })
})
