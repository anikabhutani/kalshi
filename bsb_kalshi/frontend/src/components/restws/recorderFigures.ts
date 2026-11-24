/** Plotly figures for the M6 recorder, shared by the REST vs WS page and the export gallery. */

import type { Data } from 'plotly.js-dist-min'
import type { RecorderResult, RestPoll, WsEvent } from '@/lib/api'
import { CHART_COLORS, plotTime } from '@/lib/chartTheme'
import type { Figure } from '@/lib/figures'

const msTime = (ms: number) => plotTime(ms / 1000)

/** Successful polls with a price state, as counted by the backend. */
function okPolls(result: RecorderResult): RestPoll[] {
  return result.polls.filter((p) => p.status === 200 && (p.yes_bid !== null || p.yes_ask !== null || p.last_price !== null))
}

/** Polls whose state differs from the previous successful poll. */
function restChangePolls(result: RecorderResult): RestPoll[] {
  const changed: RestPoll[] = []
  let prev: RestPoll | null = null
  for (const p of okPolls(result)) {
    if (prev !== null && (p.yes_bid !== prev.yes_bid || p.yes_ask !== prev.yes_ask || p.last_price !== prev.last_price)) changed.push(p)
    prev = p
  }
  return changed
}

const WS_TYPE_COLORS: Record<string, string> = {
  ticker: CHART_COLORS.primary,
  trade: CHART_COLORS.amber,
  orderbook_snapshot: CHART_COLORS.violet,
  orderbook_delta: CHART_COLORS.violet,
  error: CHART_COLORS.red,
}

function rasterTrace(name: string, times: number[], color: string, hover: string[]): Data {
  return {
    type: 'scatter',
    mode: 'markers',
    name,
    x: times.map(msTime),
    y: times.map(() => name),
    text: hover,
    marker: { symbol: 'line-ns-open', size: 14, color, line: { width: 1.5, color } },
    hovertemplate: '%{x|%H:%M:%S.%L} UTC<br>%{text}<extra>%{y}</extra>',
  }
}

/** One row per feed: every WS message by type, WS price changes, REST polls and REST-detected changes. */
export function eventTimelineFigure(result: RecorderResult): Figure | null {
  if (result.events.length === 0 && result.polls.length === 0) return null
  const data: Data[] = []
  const types = [...new Set(result.events.map((e) => e.type))]
  for (const type of types) {
    const rows = result.events.filter((e) => e.type === type)
    data.push(
      rasterTrace(
        `WS ${type}`,
        rows.map((e) => e.recv_ms),
        WS_TYPE_COLORS[type] ?? CHART_COLORS.muted,
        rows.map((e) => wsHover(e)),
      ),
    )
  }
  data.push(rasterTrace('WS price change', result.ws_change_times, CHART_COLORS.pink, result.ws_change_times.map(() => 'bid/ask/last differs from the previous ticker')))
  data.push(
    rasterTrace(
      'REST poll',
      result.polls.map((p) => p.recv_ms),
      CHART_COLORS.blue,
      result.polls.map((p) => `HTTP ${p.status ?? 'error'} · bid ${p.yes_bid ?? '–'} ask ${p.yes_ask ?? '–'} last ${p.last_price ?? '–'}`),
    ),
  )
  const restChanges = restChangePolls(result)
  data.push(rasterTrace('REST price change', restChanges.map((p) => p.recv_ms), CHART_COLORS.red, restChanges.map(() => 'polled state differs from the previous poll')))
  if (result.trade_polls.length > 0) {
    data.push(
      rasterTrace(
        'REST trades poll',
        result.trade_polls.map((p) => p.sent_ms),
        CHART_COLORS.muted,
        result.trade_polls.map((p) => `HTTP ${p.status ?? 'error'} · ${p.items ?? '–'} items, ${p.new_trades} new`),
      ),
    )
  }
  return {
    data,
    height: 140 + 40 * data.length,
    layout: {
      xaxis: { type: 'date', title: { text: 'Local receive time (UTC)' } },
      yaxis: { type: 'category', autorange: 'reversed', showgrid: false },
      showlegend: false,
      margin: { l: 150, r: 24, t: 16, b: 44 },
    },
  }
}

function wsHover(e: WsEvent): string {
  if (e.type === 'ticker') return `bid ${e.yes_bid ?? '–'} ask ${e.yes_ask ?? '–'} last ${e.last_price ?? '–'} · seq ${e.seq ?? '–'}`
  if (e.type === 'trade') return `${e.trade_id ?? ''} @ ${e.yes_price ?? '–'} × ${e.count ?? '–'}`
  if (e.type === 'error') return `code ${e.code ?? '–'}: ${e.message ?? ''}`
  return `seq ${e.seq ?? '–'}`
}

/** YES bid/ask from WS ticker messages (step lines) and REST polls (markers). */
export function priceComparisonFigure(result: RecorderResult): Figure | null {
  const ticks = result.events.filter((e) => e.type === 'ticker')
  const polls = okPolls(result)
  if (ticks.length === 0 && polls.length === 0) return null
  const line = (name: string, rows: WsEvent[], key: 'yes_bid' | 'yes_ask' | 'last_price', color: string, dash?: 'dot'): Data => ({
    type: 'scatter',
    mode: 'lines',
    name,
    x: rows.map((e) => msTime(e.recv_ms)),
    y: rows.map((e) => e[key] ?? null),
    line: { shape: 'hv', color, width: 1.5, dash },
    hovertemplate: `%{x|%H:%M:%S.%L} UTC<br>${name}: %{y}<extra></extra>`,
  })
  const markers = (name: string, key: 'yes_bid' | 'yes_ask' | 'last_price', color: string, symbol: 'diamond' | 'circle-open'): Data => ({
    type: 'scatter',
    mode: 'markers',
    name,
    x: polls.map((p) => msTime(p.recv_ms)),
    y: polls.map((p) => p[key]),
    marker: { color, size: 8, symbol, line: { width: 1, color: '#0b0d10' } },
    hovertemplate: `%{x|%H:%M:%S.%L} UTC<br>${name}: %{y}<extra></extra>`,
  })
  return {
    height: 360,
    data: [
      line('WS yes_bid', ticks, 'yes_bid', CHART_COLORS.primary),
      line('WS yes_ask', ticks, 'yes_ask', CHART_COLORS.amber),
      line('WS last (price_dollars)', ticks, 'last_price', CHART_COLORS.violet, 'dot'),
      markers('REST yes_bid', 'yes_bid', CHART_COLORS.primary, 'diamond'),
      markers('REST yes_ask', 'yes_ask', CHART_COLORS.amber, 'diamond'),
      markers('REST last (last_price_dollars)', 'last_price', CHART_COLORS.violet, 'circle-open'),
    ],
    layout: {
      xaxis: { type: 'date', title: { text: 'Local receive time (UTC)' } },
      yaxis: { title: { text: 'Price ($)' } },
    },
  }
}

/** Distribution of local receive time minus ts_ms per message type, and minus sending_ts_ms. */
export function latencyHistogramFigure(result: RecorderResult): Figure | null {
  const data: Data[] = []
  const types = [...new Set(result.events.map((e) => e.type))]
  for (const type of types) {
    const values = result.events.filter((e) => e.type === type && e.ts_ms != null).map((e) => e.recv_ms - (e.ts_ms as number))
    if (values.length === 0) continue
    data.push({
      type: 'histogram',
      name: `${type}: receive − ts_ms`,
      x: values,
      opacity: 0.65,
      marker: { color: WS_TYPE_COLORS[type] ?? CHART_COLORS.muted },
      hovertemplate: '%{x} ms<br>%{y} messages<extra>%{fullData.name}</extra>',
    })
  }
  const sending = result.events.filter((e) => e.sending_ts_ms != null).map((e) => e.recv_ms - (e.sending_ts_ms as number))
  if (sending.length > 0) {
    data.push({
      type: 'histogram',
      name: 'all: receive − sending_ts_ms',
      x: sending,
      opacity: 0.5,
      marker: { color: CHART_COLORS.blue },
      hovertemplate: '%{x} ms<br>%{y} messages<extra>%{fullData.name}</extra>',
    })
  }
  if (data.length === 0) return null
  return {
    data,
    height: 340,
    layout: {
      barmode: 'overlay',
      xaxis: { title: { text: 'Milliseconds (includes local clock offset)' } },
      yaxis: { title: { text: 'Messages' } },
    },
  }
}

function cumulative(name: string, times: number[], color: string, dash?: 'dot' | 'dash'): Data {
  const sorted = [...times].sort((a, b) => a - b)
  return {
    type: 'scatter',
    mode: 'lines',
    name,
    x: sorted.map(msTime),
    y: sorted.map((_, i) => i + 1),
    line: { shape: 'hv', color, width: 2, dash },
    hovertemplate: `%{x|%H:%M:%S} UTC<br>${name}: %{y}<extra></extra>`,
  }
}

/** Cumulative counts over time: WS messages, WS price changes, REST polls, REST-detected changes. */
export function cumulativeUpdatesFigure(result: RecorderResult): Figure | null {
  if (result.events.length === 0 && result.polls.length === 0) return null
  const restChanges = restChangePolls(result)
  return {
    height: 340,
    data: [
      cumulative('WS messages', result.events.map((e) => e.recv_ms), CHART_COLORS.muted, 'dot'),
      cumulative('WS price changes', result.ws_change_times, CHART_COLORS.primary),
      cumulative('REST polls', result.polls.map((p) => p.recv_ms), CHART_COLORS.blue, 'dot'),
      cumulative('REST price changes detected', restChanges.map((p) => p.recv_ms), CHART_COLORS.red),
    ],
    layout: {
      xaxis: { type: 'date', title: { text: 'Local receive time (UTC)' } },
      yaxis: { title: { text: 'Cumulative count' }, rangemode: 'tozero' },
    },
  }
}
