import { describe, expect, it } from 'vitest'

import { formatRatio, formatScore, scoreFromComponents, scoreTone } from './score'

describe('nota de qualidade', () => {
  it('reproduz a fórmula documentada a partir dos componentes', () => {
    const weights = { validity: 0.4, completeness: 0.4, uniqueness: 0.2 }
    expect(
      scoreFromComponents({ validity: 0.938, completeness: 0.99574, uniqueness: 0.95096 }, weights),
    ).toBe(96.4)
    expect(scoreFromComponents({ validity: 1, completeness: 1, uniqueness: 1 }, weights)).toBe(100)
  })

  it('formata em pt-BR e indica ausência de relatório', () => {
    expect(formatScore(96.4)).toBe('96,4')
    expect(formatScore(null)).toBe('—')
    expect(formatRatio(0.9957)).toBe('99,6%')
    expect(scoreTone(95)).toBe('success')
    expect(scoreTone(75)).toBe('warning')
    expect(scoreTone(40)).toBe('danger')
    expect(scoreTone(null)).toBe('neutral')
  })
})
