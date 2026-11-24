/** Plotly figures for the M7 sportsbook overlay. */

import type { Data, Layout } from 'plotly.js-dist-min'
import type { OverlayResult } from '@/lib/api'
import { CHART_COLORS, plotTime } from '@/lib/chartTheme'
import type { Figure } from '@/lib/figures'

const BOOK_COLORS = [CHART_COLORS.amber, CHART_COLORS.blue, CHART_COLORS.pink, CHART_COLORS.violet, CHART_COLORS.red]

function dummyWatermark(result: OverlayResult): Partial<Layout>['annotations'] {
  if (!result.is_dummy) return []
  return [
    {
      text: 'DUMMY DATA',
      xref: 'paper',
      yref: 'paper',
      x: 0.5,
      y: 0.5,
      showarrow: false,
      font: { size: 56, color: 'rgba(251,191,36,0.18)' },
    },
  ]
}

function books(result: OverlayResult): string[] {
  return [...new Set(result.rows.map((r) => r.book))]
}

/** Kalshi YES price as probability (step line) with each book's no-vig and raw implied probability. */
export function overlayFigure(result: OverlayResult): Figure | null {
  if (result.rows.length === 0) return null
  const data: Data[] = [
    {
      type: 'scatter',
      mode: 'lines',
      name: `Kalshi ${result.market_ticker ?? ''} · ${result.series.label}`,
      x: result.kalshi_points.map((p) => plotTime(p.ts)),
      y: result.kalshi_points.map((p) => p.price),
      line: { shape: 'hv', color: CHART_COLORS.primary, width: 2 },
      hovertemplate: '%{x|%Y-%m-%d %H:%M:%S} UTC<br>Kalshi %{y:.3f}<extra></extra>',
    },
  ]
  books(result).forEach((book, i) => {
    const rows = result.rows.filter((r) => r.book === book)
    const color = BOOK_COLORS[i % BOOK_COLORS.length]
    data.push(
      {
        type: 'scatter',
        mode: 'lines+markers',
        name: `${book}: no-vig`,
        x: rows.map((r) => plotTime(r.ts)),
        y: rows.map((r) => r.no_vig_prob),
        line: { color, width: 1.5 },
        marker: { color, size: 6 },
        hovertemplate: `%{x|%Y-%m-%d %H:%M:%S} UTC<br>${book} no-vig %{y:.3f}<extra></extra>`,
      },
      {
        type: 'scatter',
        mode: 'markers',
        name: `${book}: implied (with vig)`,
        x: rows.map((r) => plotTime(r.ts)),
        y: rows.map((r) => r.implied_prob),
        marker: { color, size: 5, symbol: 'circle-open' },
        visible: 'legendonly',
        hovertemplate: `%{x|%Y-%m-%d %H:%M:%S} UTC<br>${book} implied %{y:.3f}<extra></extra>`,
      },
    )
  })
  return {
    data,
    height: 480,
    layout: {
      margin: { l: 56, r: 24, t: 80, b: 44 },
      legend: { orientation: 'h', y: 1.2, x: 0, font: { size: 11 } },
      xaxis: { type: 'date', title: { text: 'UTC' } },
      yaxis: { title: { text: 'Probability' }, range: [0, 1] },
      annotations: dummyWatermark(result),
    },
  }
}

/** Gap (Kalshi − sportsbook no-vig, percentage points) at each matched timestamp, per book. */
export function gapFigure(result: OverlayResult): Figure | null {
  const usable = result.rows.filter((r) => r.gap_no_vig_pp !== null)
  if (usable.length === 0) return null
  return {
    height: 320,
    data: books(result).map((book, i) => {
      const rows = usable.filter((r) => r.book === book)
      return {
        type: 'scatter',
        mode: 'markers',
        name: book,
        x: rows.map((r) => plotTime(r.ts)),
        y: rows.map((r) => r.gap_no_vig_pp),
        customdata: rows.map((r) => r.staleness_s ?? 0),
        marker: { color: BOOK_COLORS[i % BOOK_COLORS.length], size: 7 },
        hovertemplate: '%{x|%Y-%m-%d %H:%M:%S} UTC<br>gap %{y:.2f} pp<br>Kalshi price age %{customdata:.0f} s<extra>%{fullData.name}</extra>',
      } satisfies Data
    }),
    layout: {
      xaxis: { type: 'date', title: { text: 'UTC' } },
      yaxis: { title: { text: 'Kalshi − no-vig (pp)' }, zeroline: true },
      annotations: dummyWatermark(result),
    },
  }
}
