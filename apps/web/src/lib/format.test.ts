import { describe, expect, it } from 'vitest'

import {
  formatBoolean,
  formatBytes,
  formatDate,
  formatDecimal,
  formatDuration,
  formatInteger,
  formatNaiveDateTime,
} from './format'

describe('formatação pt-BR por tipo', () => {
  it('formata decimais recebidos como texto sem perder precisão nem virar moeda', () => {
    expect(formatDecimal('1234567.50')).toBe('1.234.567,50')
    expect(formatDecimal('0.10')).toBe('0,10')
    expect(formatDecimal('-9876543210987654321.123456')).toBe('-9.876.543.210.987.654.321,123456')
    expect(formatDecimal('1234.50')).not.toContain('R$')
  })

  it('formata inteiros, inclusive grandes enviados como texto', () => {
    expect(formatInteger(1234567)).toBe('1.234.567')
    expect(formatInteger('9223372036854775807')).toBe('9.223.372.036.854.775.807')
    expect(formatInteger(null)).toBe('—')
  })

  it('formata datas sem deslocamento de fuso', () => {
    expect(formatDate('2025-01-31')).toBe('31/01/2025')
    expect(formatNaiveDateTime('2025-01-31T23:59:58')).toBe('31/01/2025 23:59:58')
  })

  it('formata booleanos, bytes e durações', () => {
    expect(formatBoolean(true)).toBe('Sim')
    expect(formatBoolean(false)).toBe('Não')
    expect(formatBytes(1536)).toBe('1,5 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5 MB')
    expect(formatDuration(450)).toBe('450 ms')
    expect(formatDuration(65_000)).toBe('1 min 5 s')
  })
})
