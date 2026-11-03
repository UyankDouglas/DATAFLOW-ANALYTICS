import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { ColumnSpec, Rule } from '@/types/api'

import { RuleEditor } from './rule-editor'

const schema: ColumnSpec[] = [
  { name: 'equipe', data_type: 'text' },
  { name: 'valor', data_type: 'decimal', scale: 2 },
]

/** Editor controlado, como na página: cada alteração volta como nova regra. */
function Harness({ initial, onRule }: { initial: Rule; onRule: (rule: Rule) => void }) {
  const [rule, setRule] = useState(initial)
  return (
    <RuleEditor
      rule={rule}
      schema={schema}
      onChange={(next) => {
        setRule(next)
        onRule(next)
      }}
    />
  )
}

describe('RuleEditor', () => {
  it('aceita listas de valores com separador digitado aos poucos', async () => {
    const onRule = vi.fn()
    render(
      <Harness
        initial={{
          operation: 'filter_rows',
          enabled: true,
          match: 'all',
          conditions: [{ column: 'equipe', operator: 'in', values: [] }],
        }}
        onRule={onRule}
      />,
    )
    await userEvent.type(screen.getByLabelText('Valores (separados por ;)'), 'Norte; Sul')
    expect(screen.getByLabelText('Valores (separados por ;)')).toHaveValue('Norte; Sul')
    const last = onRule.mock.calls.at(-1)?.[0] as Extract<Rule, { operation: 'filter_rows' }>
    expect(last.conditions[0]?.values).toEqual(['Norte', 'Sul'])
  })

  it('renomeia só as colunas preenchidas', async () => {
    const onRule = vi.fn()
    render(
      <Harness
        initial={{ operation: 'rename_columns', enabled: true, mapping: {} }}
        onRule={onRule}
      />,
    )
    await userEvent.type(screen.getByLabelText('Novo nome para valor'), 'valor_total')
    expect(onRule.mock.calls.at(-1)?.[0]).toMatchObject({ mapping: { valor: 'valor_total' } })
    await userEvent.clear(screen.getByLabelText('Novo nome para valor'))
    expect((onRule.mock.calls.at(-1)?.[0] as { mapping: object }).mapping).toEqual({})
  })

  it('oferece só colunas de texto para limpeza de espaços', () => {
    render(
      <Harness
        initial={{ operation: 'trim', enabled: true, columns: [], collapse_internal: true }}
        onRule={vi.fn()}
      />,
    )
    expect(screen.getByRole('checkbox', { name: 'equipe' })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'valor' })).not.toBeInTheDocument()
  })
})
