import type { Job } from '@/lib/api'
import { fmtUtc } from '@/lib/format'

/** Display label for a stored Timestamp Lab (M3) run. */
export function labRunLabel(job: Job<null>): string {
  const ticker = typeof job.params.market_ticker === 'string' ? job.params.market_ticker : 'market'
  return `${ticker} · ${fmtUtc(job.started_at, false)} · job ${job.id.slice(0, 8)}`
}
