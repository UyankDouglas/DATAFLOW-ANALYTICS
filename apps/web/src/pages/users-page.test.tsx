import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { bodiesOf, mockApi } from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'

import { UsersPage } from './users-page'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
afterEach(() => vi.unstubAllGlobals())

const members = [
  {
    id: 'm1',
    user_id: 'u',
    full_name: 'Ana',
    email: 'a@example.com',
    role: 'admin',
    joined_at: '2026-11-01T10:00:00Z',
  },
  {
    id: 'm2',
    user_id: 'u2',
    full_name: 'Bruno',
    email: 'b@example.com',
    role: 'viewer',
    joined_at: '2026-11-02T10:00:00Z',
  },
]
const invitation = {
  id: 'i1',
  email: 'nova@example.com',
  role: 'analyst',
  invited_by_name: 'Ana',
  created_at: '2026-11-03T10:00:00Z',
  expires_at: new Date(Date.now() + 6 * 86400_000).toISOString(),
}

describe('UsersPage', () => {
  it('administrador convida, cancela convites e remove membros', async () => {
    let pending = [invitation]
    const fetchMock = mockApi(['members:view', 'members:manage'], {
      'GET /workspaces/current/members': () => jsonResponse(members),
      'GET /workspaces/current/invitations': () => jsonResponse(pending),
      'POST /workspaces/current/invitations': () => jsonResponse({ message: 'ok' }, 202),
      'DELETE /workspaces/current/invitations/i1': () => {
        pending = []
        return new Response(null, { status: 204 })
      },
      'DELETE /workspaces/current/members/m2': () => new Response(null, { status: 204 }),
    })
    renderWithProviders(<UsersPage />)
    expect(await screen.findByText('nova@example.com')).toBeInTheDocument()
    expect(await screen.findByText('(você)')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('E-mail'), 'outra@example.com')
    await userEvent.click(screen.getByRole('button', { name: /Convidar/ }))
    await waitFor(() =>
      expect(bodiesOf(fetchMock, 'POST /workspaces/current/invitations')).toEqual([
        { email: 'outra@example.com', role: 'analyst' },
      ]),
    )

    await userEvent.click(screen.getByRole('button', { name: 'Cancelar convite' }))
    await waitFor(() => expect(screen.queryByText('nova@example.com')).toBeNull())

    await userEvent.click(screen.getByRole('button', { name: 'Remover Bruno' }))
    expect(screen.getByText(/perde o acesso a este workspace/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remover do workspace' }))
    await waitFor(() =>
      expect(bodiesOf(fetchMock, 'DELETE /workspaces/current/members/m2')).toHaveLength(1),
    )
  })

  it('analista vê os membros, mas não convida nem altera', async () => {
    mockApi(['members:view'], {
      'GET /workspaces/current/members': () => jsonResponse(members),
    })
    renderWithProviders(<UsersPage />)
    expect(await screen.findByText('Bruno')).toBeInTheDocument()
    expect(screen.queryByText('Convidar pessoas')).toBeNull()
    expect(screen.queryByRole('button', { name: /Remover/ })).toBeNull()
    expect(screen.queryByRole('combobox', { name: /Perfil de/ })).toBeNull()
    expect(screen.getByText('Visualizador')).toBeInTheDocument()
  })
})
