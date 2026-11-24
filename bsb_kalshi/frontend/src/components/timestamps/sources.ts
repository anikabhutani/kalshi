import type { CandleSource, GapStats, LabResult, OrderbookSource, TradeSource } from '@/lib/api'

export function candleSources(result: LabResult): CandleSource[] {
  return Object.values(result.sources)
    .filter((s): s is CandleSource => s.kind === 'candles')
    .sort((a, b) => a.interval_min - b.interval_min)
}

export function tradeSource(result: LabResult): TradeSource | null {
  return Object.values(result.sources).find((s): s is TradeSource => s.kind === 'trades') ?? null
}

export function orderbookSource(result: LabResult): OrderbookSource | null {
  return Object.values(result.sources).find((s): s is OrderbookSource => s.kind === 'orderbook') ?? null
}

export const candleLabel = (interval: number) =>
  interval % 1440 === 0 ? `${interval / 1440}d candles` : interval % 60 === 0 ? `${interval / 60}h candles` : `${interval}m candles`

export interface GapSeries {
  label: string
  /** "missing": no record at all in the slot; "no-trade": no trade in the slot. */
  kind: 'missing' | 'no-trade'
  stats: GapStats
}

/** Every gap analysis in a run, labelled for charts and tables. */
export function gapSeries(result: LabResult): GapSeries[] {
  const series: GapSeries[] = []
  for (const c of candleSources(result)) {
    const name = candleLabel(c.interval_min)
    series.push({ label: `${name}: missing periods`, kind: 'missing', stats: c.metrics.missing_periods })
    series.push({ label: `${name}: periods without a trade`, kind: 'no-trade', stats: c.metrics.periods_without_trade })
  }
  const trades = tradeSource(result)
  if (trades !== null) {
    series.push({
      label: `trades: empty ${trades.metrics.bucket_s}s buckets`,
      kind: 'no-trade',
      stats: trades.metrics.empty_buckets,
    })
  }
  return series
}
