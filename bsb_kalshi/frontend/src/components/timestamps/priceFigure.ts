import type { Data, Layout } from 'plotly.js-dist-min'
import type { LabResult } from '@/lib/api'
import { CHART_COLORS, plotTime } from '@/lib/chartTheme'
import { candleLabel, candleSources, orderbookSource, tradeSource } from '@/components/timestamps/sources'

const INTERVAL_COLORS = [CHART_COLORS.primary, CHART_COLORS.violet, CHART_COLORS.pink]

export interface PriceChartOptions {
  interval: number
  style: 'line' | 'candles'
  showBidAsk: boolean
  showTrades: boolean
}

/** Price traces for one Timestamp Lab result (the gallery uses the defaults: first interval, line view). */
export function priceTraces(result: LabResult, options?: Partial<PriceChartOptions>): Data[] {
  const candles = candleSources(result)
  const trades = tradeSource(result)
  const book = orderbookSource(result)
  const interval = options?.interval ?? candles[0]?.interval_min ?? 1
  const style = options?.style ?? 'line'
  const showBidAsk = options?.showBidAsk ?? true
  const showTrades = options?.showTrades ?? true
  const selected = candles.find((c) => c.interval_min === interval) ?? candles[0]
  const traces: Data[] = []
  if (style === 'candles' && selected !== undefined) {
    const priced = selected.rows.filter((r) => r.close !== null)
    traces.push({
      type: 'candlestick',
      name: `${candleLabel(selected.interval_min)} OHLC`,
      x: priced.map((r) => plotTime(r.ts)),
      open: priced.map((r) => r.open),
      high: priced.map((r) => r.high),
      low: priced.map((r) => r.low),
      close: priced.map((r) => r.close),
      increasing: { line: { color: CHART_COLORS.primary } },
      decreasing: { line: { color: CHART_COLORS.red } },
    })
  } else {
    candles.forEach((c, i) =>
      traces.push({
        type: 'scatter',
        mode: c.rows.length > 200 ? 'lines' : 'lines+markers',
        name: `${candleLabel(c.interval_min)} close`,
        x: c.rows.map((r) => plotTime(r.ts)),
        y: c.rows.map((r) => r.close),
        line: { color: INTERVAL_COLORS[i % INTERVAL_COLORS.length], width: c.interval_min === interval ? 2 : 1, shape: 'hv' },
        hovertemplate: '%{x|%Y-%m-%d %H:%M:%S} UTC<br>close $%{y:.4f}<extra>%{fullData.name}</extra>',
      }),
    )
  }
  if (showBidAsk && selected !== undefined) {
    for (const [field, label, color] of [
      ['bid_close', 'YES bid close', CHART_COLORS.blue],
      ['ask_close', 'YES ask close', CHART_COLORS.amber],
    ] as const) {
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: `${candleLabel(selected.interval_min)} ${label}`,
        x: selected.rows.map((r) => plotTime(r.ts)),
        y: selected.rows.map((r) => r[field]),
        line: { color, width: 1, dash: 'dot', shape: 'hv' },
        hovertemplate: `%{x|%Y-%m-%d %H:%M:%S} UTC<br>${label} $%{y:.4f}<extra></extra>`,
      })
    }
  }
  if (showTrades && trades !== null && trades.rows.length > 0) {
    traces.push({
      type: 'scattergl',
      mode: 'markers',
      name: 'Trades (yes price)',
      x: trades.rows.map((r) => plotTime(r.ts)),
      y: trades.rows.map((r) => r.price),
      customdata: trades.rows.map((r) => [r.count ?? 0, r.side ?? '–']),
      marker: { color: CHART_COLORS.muted, size: 4, opacity: 0.55 },
      hovertemplate: '%{x|%Y-%m-%d %H:%M:%S.%L} UTC<br>$%{y:.4f} · count %{customdata[0]} · %{customdata[1]}<extra>trade</extra>',
    })
  }
  if (book?.mid !== null && book?.mid !== undefined) {
    traces.push({
      type: 'scatter',
      mode: 'markers',
      name: 'Orderbook mid (snapshot)',
      x: [plotTime(book.snapshot_ts)],
      y: [book.mid],
      marker: { color: CHART_COLORS.amber, size: 11, symbol: 'diamond' },
    })
  }
  if (selected !== undefined) {
    traces.push({
      type: 'bar',
      name: `${candleLabel(selected.interval_min)} volume`,
      x: selected.rows.map((r) => plotTime(r.ts)),
      y: selected.rows.map((r) => r.volume),
      yaxis: 'y2',
      marker: { color: 'rgba(52,211,153,0.45)' },
      hovertemplate: '%{x|%Y-%m-%d %H:%M} UTC<br>volume %{y}<extra></extra>',
    })
  }
  return traces
}

/** Price axis on top, volume below, and an optional vertical marker line. */
export function priceLayout(markerTs: number | null): Partial<Layout> {
  return {
    xaxis: { type: 'date', anchor: 'y2', rangeslider: { visible: false }, title: { text: 'UTC' } },
    yaxis: { domain: [0.3, 1], title: { text: 'Price ($)' } },
    yaxis2: { domain: [0, 0.22], title: { text: 'Volume' } },
    shapes:
      markerTs === null
        ? []
        : [
            {
              type: 'line',
              xref: 'x',
              yref: 'paper',
              x0: plotTime(markerTs),
              x1: plotTime(markerTs),
              y0: 0,
              y1: 1,
              line: { color: CHART_COLORS.amber, width: 1, dash: 'dash' },
            },
          ],
  }
}
