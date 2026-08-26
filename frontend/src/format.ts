/**
 * Number formatting (FR-8.11).
 *
 * Indian numbering throughout (lakh/crore), rupee symbol on monetary values,
 * percentages to two decimals.
 *
 * Colour is never the sole carrier of gain/loss information — every signed
 * value also gets an arrow glyph, so the meaning survives greyscale printing
 * and colour-vision differences (NFR-6.3).
 */

const INR = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })
const INR0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

export const EM_DASH = '—'

export function isBlank(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === 'number' && !isFinite(value))
}

export function num(value: number | null | undefined, decimals = 2): string {
  if (isBlank(value)) return EM_DASH
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value as number)
}

export function currency(value: number | null | undefined, decimals = 2): string {
  if (isBlank(value)) return EM_DASH
  return `₹${new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value as number)}`
}

/** Compact rupee amounts in lakh/crore, the convention the operator reads in. */
export function currencyCompact(value: number | null | undefined): string {
  if (isBlank(value)) return EM_DASH
  const v = value as number
  const abs = Math.abs(v)
  if (abs >= 1e7) return `₹${INR.format(v / 1e7)} Cr`
  if (abs >= 1e5) return `₹${INR.format(v / 1e5)} L`
  if (abs >= 1e3) return `₹${INR0.format(v)}`
  return `₹${INR.format(v)}`
}

export function count(value: number | null | undefined): string {
  if (isBlank(value)) return EM_DASH
  const v = value as number
  const abs = Math.abs(v)
  if (abs >= 1e7) return `${INR.format(v / 1e7)} Cr`
  if (abs >= 1e5) return `${INR.format(v / 1e5)} L`
  return INR0.format(v)
}

/** Percentage from a decimal fraction: 0.0512 -> "5.12%". */
export function pct(value: number | null | undefined, decimals = 2): string {
  if (isBlank(value)) return EM_DASH
  return `${((value as number) * 100).toFixed(decimals)}%`
}

export type Direction = 'up' | 'down' | 'flat' | 'none'

export function direction(value: number | null | undefined): Direction {
  if (isBlank(value)) return 'none'
  const v = value as number
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return 'flat'
}

/** The glyph that carries sign without relying on colour. */
export function arrow(value: number | null | undefined): string {
  switch (direction(value)) {
    case 'up':
      return '▲'
    case 'down':
      return '▼'
    case 'flat':
      return '='
    default:
      return ''
  }
}

export function signedPct(value: number | null | undefined, decimals = 2): string {
  if (isBlank(value)) return EM_DASH
  const glyph = arrow(value)
  return `${glyph} ${Math.abs((value as number) * 100).toFixed(decimals)}%`
}

export function directionClass(value: number | null | undefined): string {
  switch (direction(value)) {
    case 'up':
      return 'text-[var(--up)]'
    case 'down':
      return 'text-[var(--down)]'
    default:
      return 'text-[var(--muted)]'
  }
}

export function bool(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return EM_DASH
  return value ? 'Yes' : 'No'
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return EM_DASH
  const d = new Date(value)
  if (isNaN(d.getTime())) return String(value)
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

/** Format by the unit declared in the metric registry. */
export function byUnit(value: unknown, unit: string | undefined): string {
  if (typeof value === 'boolean') return bool(value)
  if (isBlank(value)) return EM_DASH
  const v = value as number
  switch (unit) {
    case 'percent':
      return pct(v)
    case 'currency':
      return currency(v)
    case 'integer':
      return count(v)
    case 'ratio':
      return num(v, 2)
    default:
      return num(v, Math.abs(v) >= 1000 ? 0 : 2)
  }
}
