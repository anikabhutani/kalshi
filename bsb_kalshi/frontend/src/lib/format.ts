/** Display formatting. All times are shown in UTC to match the API. */

const pad = (n: number, width = 2) => String(n).padStart(width, '0')

export function fmtUtc(value: string | number | null | undefined, withSeconds = true): string {
  if (value === null || value === undefined || value === '') return '–'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const base = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
  return `${base}${withSeconds ? `:${pad(date.getUTCSeconds())}` : ''} UTC`
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '–'
  if (seconds === 0) return '0 s'
  const abs = Math.abs(seconds)
  const sign = seconds < 0 ? '−' : ''
  if (abs < 1) return `${sign}${(abs * 1000).toFixed(abs < 0.01 ? 2 : 0)} ms`
  if (abs < 60) return `${sign}${abs.toFixed(abs < 10 ? 2 : 1)} s`
  const units: [number, string][] = [
    [86_400, 'd'],
    [3_600, 'h'],
    [60, 'm'],
    [1, 's'],
  ]
  const parts: string[] = []
  let rest = Math.round(abs)
  for (const [size, label] of units) {
    if (rest >= size) {
      parts.push(`${Math.floor(rest / size)}${label}`)
      rest %= size
    }
    if (parts.length === 2) break
  }
  return sign + parts.join(' ')
}

export function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '–'
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtPct(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : `${value.toFixed(1)}%`
}

export function fmtPrice(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : `$${value.toFixed(4)}`
}

/** Unix seconds -> value for an <input type="datetime-local"> interpreted as UTC. */
export function toUtcInput(epochS: number): string {
  const d = new Date(epochS * 1000)
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
}

/** <input type="datetime-local"> value interpreted as UTC -> unix seconds (null if invalid). */
export function fromUtcInput(value: string): number | null {
  if (!value) return null
  const ms = Date.parse(`${value.length === 16 ? `${value}:00` : value}Z`)
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000)
}
