/** Pure Plotly figure builders shared by module pages and the export chart gallery. */

import type { Data, Layout, Shape } from 'plotly.js-dist-min'
import type { DepthResult, MatrixCell, PaginationResult, RampResult } from '@/lib/api'
import { CHART_COLORS, plotTime } from '@/lib/chartTheme'

export interface Figure {
  data: Data[]
  layout: Partial<Layout>
  height: number
}

const PROBE_STYLES = [
  { key: 'found', name: 'Probe: records before bound', color: CHART_COLORS.primary },
  { key: 'empty', name: 'Probe: no records before bound', color: CHART_COLORS.muted },
  { key: 'error', name: 'Probe: HTTP error', color: CHART_COLORS.red },
] as const

/** Per endpoint: observed oldest→newest range, the bisection bracket, each probe, and cutoff lines. */
export function depthTimelineFigure(result: DepthResult): Figure | null {
  const targets = result.targets.filter((t) => t.oldest_ts != null || (t.probes?.length ?? 0) > 0)
  if (targets.length === 0) return null
  const data: Data[] = []
  let rangeLegend = true
  let bracketLegend = true
  for (const t of targets) {
    if (t.bracket_lo != null && t.bracket_hi != null) {
      data.push({
        type: 'scatter',
        mode: 'lines',
        name: 'Oldest record lies in this bracket',
        legendgroup: 'bracket',
        showlegend: bracketLegend,
        x: [plotTime(t.bracket_lo), plotTime(t.bracket_hi)],
        y: [t.label, t.label],
        line: { color: CHART_COLORS.amber, width: 18 },
        opacity: 0.55,
        hovertemplate: `${t.label}<br>bracket %{x|%Y-%m-%d %H:%M} UTC<extra></extra>`,
      })
      bracketLegend = false
    }
    if (t.oldest_ts != null && t.newest_ts != null) {
      data.push({
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Records observed (oldest → newest)',
        legendgroup: 'range',
        showlegend: rangeLegend,
        x: [plotTime(t.oldest_ts), plotTime(t.newest_ts)],
        y: [t.label, t.label],
        line: { color: CHART_COLORS.primary, width: 8 },
        marker: { size: 9, color: CHART_COLORS.primary },
        hovertemplate: `${t.label}<br>%{x|%Y-%m-%d %H:%M:%S} UTC<extra></extra>`,
      })
      rangeLegend = false
    }
  }
  for (const style of PROBE_STYLES) {
    const points = targets.flatMap((t) =>
      (t.probes ?? [])
        .filter((p) => p.bound !== null)
        .filter((p) => {
          const ok = p.status !== null && p.status >= 200 && p.status < 300
          return style.key === 'error' ? !ok : ok && (style.key === 'found') === p.records > 0
        })
        .map((p) => ({ label: t.label, bound: p.bound as number, status: p.status })),
    )
    if (points.length === 0) continue
    data.push({
      type: 'scatter',
      mode: 'markers',
      name: style.name,
      x: points.map((p) => plotTime(p.bound)),
      y: points.map((p) => p.label),
      customdata: points.map((p) => p.status ?? 'error'),
      marker: { symbol: 'line-ns-open', size: 16, color: style.color, line: { width: 2, color: style.color } },
      hovertemplate: 'bound %{x|%Y-%m-%d %H:%M:%S} UTC<br>HTTP %{customdata}<extra>%{y}</extra>',
    })
  }
  const shapes: Partial<Shape>[] = []
  const annotations: Partial<Layout>['annotations'] = []
  for (const [field, value] of Object.entries(result.cutoff)) {
    if (value.epoch_s === null) continue
    shapes.push({
      type: 'line',
      xref: 'x',
      yref: 'paper',
      x0: plotTime(value.epoch_s),
      x1: plotTime(value.epoch_s),
      y0: 0,
      y1: 1,
      line: { color: CHART_COLORS.pink, width: 1, dash: 'dash' },
    })
    annotations.push({
      x: plotTime(value.epoch_s),
      y: 1,
      xref: 'x',
      yref: 'paper',
      text: field,
      showarrow: false,
      textangle: -90,
      xanchor: 'right',
      yanchor: 'top',
      font: { size: 10, color: CHART_COLORS.pink },
    })
  }
  return {
    data,
    height: 160 + 56 * targets.length,
    layout: {
      xaxis: { type: 'date', title: { text: 'UTC' } },
      yaxis: { type: 'category', autorange: 'reversed', showgrid: false },
      shapes,
      annotations,
      margin: { l: 220, r: 24, t: 40, b: 44 },
    },
  }
}

function cellScore(cell: MatrixCell | undefined): number | null {
  if (cell === undefined || cell.status === null) return null
  if (cell.status < 200 || cell.status >= 300) return 0
  return (cell.records ?? 0) > 0 ? 2 : 1
}

/** Archive matrix: sample markets x endpoint checks, colored by HTTP status / records returned. */
export function archiveMatrixFigure(result: DepthResult): Figure | null {
  const samples = result.matrix?.samples ?? []
  if (samples.length === 0) return null
  const checks = [...new Set(samples.flatMap((s) => s.cells.map((c) => c.check)))]
  const y = samples.map((s) => `${s.ticker} (${s.cutoff_side ?? '–'})`)
  const cellsFor = samples.map((s) => checks.map((check) => s.cells.find((c) => c.check === check)))
  return {
    height: 140 + 64 * samples.length,
    data: [
      {
        type: 'heatmap',
        x: checks,
        y,
        z: cellsFor.map((row) => row.map(cellScore)),
        text: cellsFor.map((row) =>
          row.map((c) => (c === undefined ? '' : c.status === null ? (c.note ?? 'not checked') : `HTTP ${c.status} · ${c.records ?? 0} rec`)),
        ) as unknown as string[],
        texttemplate: '%{text}',
        zmin: 0,
        zmax: 2,
        colorscale: [
          [0, 'rgba(248,113,113,0.55)'],
          [0.5, 'rgba(154,160,171,0.3)'],
          [1, 'rgba(52,211,153,0.7)'],
        ],
        showscale: false,
        xgap: 3,
        ygap: 3,
        hovertemplate: '%{y}<br>%{x}<br>%{text}<extra></extra>',
      },
    ],
    layout: {
      xaxis: { showgrid: false, tickangle: -20 },
      yaxis: { showgrid: false, autorange: 'reversed' },
      margin: { l: 260, r: 24, t: 16, b: 90 },
    },
  }
}

const rateLabel = (rps: number) => `${rps} req/s`

/** Latency distribution per target request rate, with the first 429 marked. */
export function latencyVsRateFigure(result: RampResult): Figure | null {
  const ok = result.requests.filter((r) => r.latency_ms !== null)
  if (ok.length === 0) return null
  const data: Data[] = [
    {
      type: 'box',
      name: 'Latency',
      x: ok.map((r) => rateLabel(r.target_rps)),
      y: ok.map((r) => r.latency_ms),
      boxpoints: 'all',
      jitter: 0.4,
      pointpos: 0,
      marker: { color: CHART_COLORS.primary, size: 4 },
      line: { color: CHART_COLORS.primary },
      hovertemplate: '%{x}<br>%{y:.0f} ms<extra></extra>',
    },
    {
      type: 'scatter',
      mode: 'lines+markers',
      name: 'Achieved rate',
      x: result.steps.map((s) => rateLabel(s.target_rps)),
      y: result.steps.map((s) => s.achieved_rps),
      yaxis: 'y2',
      line: { color: CHART_COLORS.blue, dash: 'dot' },
      hovertemplate: '%{x}<br>achieved %{y:.2f} req/s<extra></extra>',
    },
  ]
  if (result.first_429) {
    const maxLatency = Math.max(...ok.map((r) => r.latency_ms ?? 0))
    data.push({
      type: 'scatter',
      mode: 'markers',
      name: 'First HTTP 429',
      x: [rateLabel(result.first_429.target_rps)],
      y: [maxLatency],
      marker: { symbol: 'x', size: 14, color: CHART_COLORS.red },
    })
  }
  return {
    data,
    height: 380,
    layout: {
      xaxis: { title: { text: 'Target request rate' }, type: 'category' },
      yaxis: { title: { text: 'Latency (ms)' }, rangemode: 'tozero' },
      yaxis2: { title: { text: 'Achieved req/s' }, overlaying: 'y', side: 'right', showgrid: false, rangemode: 'tozero' },
    },
  }
}

/** Latency of every ramp request against its send time, colored by step. */
export function rampTimelineFigure(result: RampResult): Figure | null {
  if (result.requests.length === 0) return null
  const colors = Object.values(CHART_COLORS)
  return {
    height: 320,
    data: result.steps.map((step, i) => {
      const rows = result.requests.filter((r) => r.target_rps === step.target_rps)
      return {
        type: 'scatter',
        mode: 'markers',
        name: rateLabel(step.target_rps),
        x: rows.map((r) => r.t_s),
        y: rows.map((r) => r.latency_ms ?? 0),
        customdata: rows.map((r) => r.status ?? 'error'),
        marker: {
          color: rows.map((r) => (r.status === 429 ? CHART_COLORS.red : colors[i % colors.length])),
          size: rows.map((r) => (r.status === 429 ? 12 : 7)),
          symbol: rows.map((r) => (r.status === 429 ? 'x' : 'circle')),
        },
        hovertemplate: 't=%{x:.2f}s<br>%{y:.0f} ms · HTTP %{customdata}<extra>%{fullData.name}</extra>',
      } satisfies Data
    }),
    layout: {
      xaxis: { title: { text: 'Seconds since job start (send time)' } },
      yaxis: { title: { text: 'Latency (ms)' }, rangemode: 'tozero' },
    },
  }
}

/** Numeric rate-limit-like response header values over time (null when none were returned). */
export function headerValuesFigure(result: RampResult): Figure | null {
  const names = [...new Set(result.requests.flatMap((r) => Object.keys(r.rate_headers ?? {})))]
  const series = names
    .map((name) => {
      const rows = result.requests.filter((r) => r.rate_headers?.[name] !== undefined && Number.isFinite(Number(r.rate_headers[name])))
      return { name, rows }
    })
    .filter((s) => s.rows.length > 0)
  if (series.length === 0) return null
  return {
    height: 320,
    data: series.map((s) => ({
      type: 'scatter',
      mode: 'lines+markers',
      name: s.name,
      x: s.rows.map((r) => r.t_s),
      y: s.rows.map((r) => Number(r.rate_headers?.[s.name])),
      line: { shape: 'hv' },
      hovertemplate: `t=%{x:.2f}s<br>${s.name}: %{y}<extra></extra>`,
    })),
    layout: {
      xaxis: { title: { text: 'Seconds since job start (send time)' } },
      yaxis: { title: { text: 'Header value' } },
    },
  }
}

/** Items and duplicates per cursor page. */
export function paginationFigure(result: PaginationResult): Figure | null {
  if (result.pages.length === 0) return null
  const x = result.pages.map((p) => `page ${p.page}`)
  return {
    height: 300,
    data: [
      {
        type: 'bar',
        name: 'Items returned',
        x,
        y: result.pages.map((p) => p.items),
        marker: { color: CHART_COLORS.primary },
      },
      {
        type: 'bar',
        name: 'Duplicates of earlier pages',
        x,
        y: result.pages.map((p) => p.duplicates_of_earlier_pages),
        marker: { color: CHART_COLORS.red },
      },
    ],
    layout: {
      barmode: 'group',
      yaxis: { title: { text: `Items (page size ${result.walk_size})` }, rangemode: 'tozero' },
      shapes: [
        {
          type: 'line',
          xref: 'paper',
          yref: 'y',
          x0: 0,
          x1: 1,
          y0: result.walk_size,
          y1: result.walk_size,
          line: { color: CHART_COLORS.amber, width: 1, dash: 'dash' },
        },
      ],
    },
  }
}
