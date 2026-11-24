/** Plotly charts for the in-game analysis page. */

import type { Data } from 'plotly.js-dist-min'
import type { IGSeason } from '@/lib/api'
import { CHART_COLORS } from '@/lib/chartTheme'
import type { Figure } from '@/lib/figures'

export const GROUPS = ['Longshot (<40¢)', 'Middle (40–60¢)', 'Favorite (60¢+)']
const PHASES = ['Pre-game', 'In-game'] as const
const PHASE_COLOR: Record<string, string> = { 'Pre-game': CHART_COLORS.muted, 'In-game': CHART_COLORS.primary }
const SEASON_COLOR: Record<number, string> = { 2025: CHART_COLORS.blue, 2026: CHART_COLORS.primary }
const pct = { tickformat: '.0%', rangemode: 'tozero' as const }
const usd10 = { tickprefix: '$', tickformat: '.2f' }
const short = (g: string): string => g.split(' (')[0] ?? g

export function timelineFigure(s: IGSeason): Figure {
  const b = s.trades!.by_bin
  const x = b.map((r) => r.bin_label)
  const data: Data[] = [
    { type: 'bar', name: 'Share of money traded', x, y: b.map((r) => r.dollar_share), marker: { color: CHART_COLORS.primary },
      hovertemplate: '%{x}<br>%{y:.1%} of dollars<extra></extra>' },
    { type: 'bar', name: 'Share of fees', x, y: b.map((r) => r.fee_share), marker: { color: CHART_COLORS.amber },
      hovertemplate: '%{x}<br>%{y:.1%} of fees<extra></extra>' },
  ]
  return {
    data,
    height: 340,
    layout: {
      barmode: 'group',
      xaxis: { title: { text: 'Time relative to kickoff' }, tickangle: -30 },
      yaxis: { title: { text: 'Share of the season' }, ...pct },
      shapes: [{ type: 'line', xref: 'x', yref: 'paper', x0: 3.5, x1: 3.5, y0: 0, y1: 1, line: { color: 'rgba(255,255,255,0.35)', dash: 'dot' } }],
      annotations: [{ x: 3.5, y: 1, xref: 'x', yref: 'paper', text: 'kickoff', showarrow: false, xanchor: 'left', font: { size: 10 } }],
    },
  }
}

export function feeRateFigure(s: IGSeason): Figure {
  const b = s.trades!.by_bin
  return {
    data: [{ type: 'bar', x: b.map((r) => r.bin_label), y: b.map((r) => r.fee_per_10), marker: { color: CHART_COLORS.amber },
      hovertemplate: '%{x}<br>$%{y:.3f} fee per $10 traded<extra></extra>' }],
    height: 300,
    layout: { xaxis: { tickangle: -30 }, yaxis: { title: { text: 'Fee per $10 traded' }, ...usd10, rangemode: 'tozero' }, showlegend: false },
  }
}

export function phaseGroupFigure(s: IGSeason): Figure {
  const rows = s.trades!.by_phase_group
  const x = PHASES.flatMap((p) => GROUPS.map((g) => `${p === 'Pre-game' ? 'Pre' : 'In'} · ${short(g)}`))
  const val = (k: 'dollar_share' | 'fee_share') =>
    PHASES.flatMap((p) => GROUPS.map((g) => rows.find((r) => r.phase === p && r.group_label === g)?.[k] ?? 0))
  return {
    data: [
      { type: 'bar', name: 'Share of money traded', x, y: val('dollar_share'), marker: { color: CHART_COLORS.primary }, hovertemplate: '%{x}<br>%{y:.1%} of dollars<extra></extra>' },
      { type: 'bar', name: 'Share of fees', x, y: val('fee_share'), marker: { color: CHART_COLORS.amber }, hovertemplate: '%{x}<br>%{y:.1%} of fees<extra></extra>' },
    ],
    height: 320,
    layout: { barmode: 'group', yaxis: { title: { text: 'Share of the season' }, ...pct } },
  }
}

export function costFigure(s: IGSeason): Figure {
  const rows = s.cost_by_phase_group ?? []
  const data: Data[] = PHASES.map((p) => ({
    type: 'bar',
    name: p,
    x: GROUPS.map(short),
    y: GROUPS.map((g) => rows.find((r) => r.phase === p && r.group_label === g)?.cost ?? null),
    customdata: GROUPS.map((g) => {
      const r = rows.find((x) => x.phase === p && x.group_label === g)
      return r ? [r.fee_part, r.spread_part, r.quotes] : [null, null, null]
    }),
    marker: { color: PHASE_COLOR[p] },
    hovertemplate: `${p}, %{x}<br>$%{y:.2f} per $10 (fee $%{customdata[0]:.2f} + spread $%{customdata[1]:.2f})<br>%{customdata[2]} quotes<extra></extra>`,
  }))
  return { data, height: 300, layout: { barmode: 'group', yaxis: { title: { text: 'Median cost per $10' }, ...usd10, rangemode: 'tozero' } } }
}

export function liquidityFigure(s: IGSeason): Figure {
  const r = (s.spread_by_minute ?? []).filter((x) => x.minute <= 210)
  return {
    data: [
      { type: 'scatter', mode: 'lines', name: 'Markets with a buy and a sell price', x: r.map((x) => x.minute), y: r.map((x) => x.two_sided_share),
        line: { color: CHART_COLORS.primary, width: 2 }, hovertemplate: '%{x} min: %{y:.0%} two-sided<extra></extra>' },
    ],
    height: 260,
    layout: {
      xaxis: { title: { text: 'Minutes from kickoff' }, zeroline: true },
      yaxis: { title: { text: 'Share two-sided' }, tickformat: '.0%', range: [0, 1.05] },
      showlegend: false,
    },
  }
}

export function brierFigure(seasons: IGSeason[]): Figure {
  const data: Data[] = seasons.flatMap((s) => {
    const r = s.calibration.by_checkpoint
    return [{
      type: 'scatter', mode: 'lines+markers', name: `${s.season} (${s.facts.settled_games} games)`,
      x: r.map((x) => x.minute), y: r.map((x) => x.brier),
      error_y: { type: 'data', symmetric: false, array: r.map((x) => x.brier_hi - x.brier), arrayminus: r.map((x) => x.brier - x.brier_lo), thickness: 1 },
      customdata: r.map((x) => x.games), line: { color: SEASON_COLOR[s.season] ?? CHART_COLORS.violet, width: 2 },
      hovertemplate: `${s.season}, %{x} min<br>Brier %{y:.3f}<br>%{customdata} games<extra></extra>`,
    } as Data]
  })
  data.push({ type: 'scatter', mode: 'lines', name: 'Coin flip (0.25)', x: [-60, 180], y: [0.25, 0.25], line: { color: CHART_COLORS.muted, dash: 'dash', width: 1 }, hoverinfo: 'skip' })
  return {
    data,
    height: 320,
    layout: {
      xaxis: { title: { text: 'Minutes from kickoff' }, tickvals: [-60, 0, 30, 60, 90, 120, 150, 180] },
      yaxis: { title: { text: 'Brier score (lower = more accurate)' }, rangemode: 'tozero' },
    },
  }
}

export function reliabilityFigure(s: IGSeason): Figure {
  const rel = s.calibration.reliability
  const colors: Record<number, string> = { [-60]: CHART_COLORS.muted, 60: CHART_COLORS.primary, 120: CHART_COLORS.amber }
  const data: Data[] = [-60, 60, 120].map((m) => {
    const r = rel.filter((x) => x.minute === m)
    return {
      type: 'scatter', mode: 'markers', name: m < 0 ? '1 h before kickoff' : `${m} min into the game`,
      x: r.map((x) => x.mean_price), y: r.map((x) => x.won), customdata: r.map((x) => x.games),
      marker: { color: colors[m], size: r.map((x) => Math.max(6, Math.min(22, Math.sqrt(x.games) * 3))), opacity: 0.85 },
      hovertemplate: 'Price %{x:.0%} → won %{y:.0%}<br>%{customdata} games<extra></extra>',
    } as Data
  })
  data.push({ type: 'scatter', mode: 'lines', name: 'Perfectly accurate', x: [0, 1], y: [0, 1], line: { color: CHART_COLORS.muted, dash: 'dash', width: 1 }, hoverinfo: 'skip' })
  return {
    data,
    height: 340,
    layout: {
      xaxis: { title: { text: 'Kalshi price (away team)' }, tickformat: '.0%', range: [-0.04, 1.04] },
      yaxis: { title: { text: 'Share that won' }, tickformat: '.0%', range: [-0.06, 1.08] },
    },
  }
}

export function returnsFigure(s: IGSeason, fees: boolean): Figure {
  const rows = s.trades!.returns_by_group
  const k = fees ? 'after' : 'before'
  const data: Data[] = PHASES.map((p) => {
    const r = GROUPS.map((g) => rows.find((x) => x.phase === p && x.group_label === g))
    const y = r.map((x) => (x ? (fees ? x.after_fees : x.before_fees) : null))
    return {
      type: 'scatter', mode: 'markers', name: p, x: GROUPS.map(short), y,
      error_y: {
        type: 'data', symmetric: false, thickness: 1.5,
        array: r.map((x, i) => (x ? (x[`${k}_hi`] as number) - (y[i] as number) : 0)),
        arrayminus: r.map((x, i) => (x ? (y[i] as number) - (x[`${k}_lo`] as number) : 0)),
      },
      marker: { color: PHASE_COLOR[p], size: 10 },
      customdata: r.map((x) => (x ? [x.avg_price, x.win_rate, x.games] : [null, null, null])),
      hovertemplate: `${p}, %{x}<br>%{y:$.2f} per $10<br>avg price %{customdata[0]:.0%}, won %{customdata[1]:.0%}<br>%{customdata[2]} games<extra></extra>`,
    } as Data
  })
  return {
    data,
    height: 320,
    layout: {
      yaxis: { title: { text: `Taker result per $10 ${fees ? 'after' : 'before'} fees` }, tickprefix: '$', zeroline: true, zerolinecolor: 'rgba(255,255,255,0.4)' },
      xaxis: { type: 'category' },
    },
  }
}

export function slotFigure(s: IGSeason): Figure {
  const order = ['Thursday night', 'Sunday early', 'Sunday late', 'Sunday night', 'Monday night', 'Saturday', 'Other day']
  const rows = order.map((o) => s.trades!.by_slot.find((x) => x.slot === o)).filter((x) => x !== undefined)
  return {
    data: [
      { type: 'bar', name: 'Before kickoff', x: rows.map((r) => r.slot), y: rows.map((r) => r.pre_per_game / 1e6), marker: { color: CHART_COLORS.muted },
        customdata: rows.map((r) => r.games), hovertemplate: '%{x}<br>$%{y:.1f}M per game before kickoff<br>%{customdata} games<extra></extra>' },
      { type: 'bar', name: 'During the game', x: rows.map((r) => r.slot), y: rows.map((r) => r.inplay_per_game / 1e6), marker: { color: CHART_COLORS.primary },
        customdata: rows.map((r) => r.games), hovertemplate: '%{x}<br>$%{y:.1f}M per game in-game<br>%{customdata} games<extra></extra>' },
    ],
    height: 300,
    layout: { barmode: 'stack', yaxis: { title: { text: 'Traded per game ($M)' }, tickprefix: '$', ticksuffix: 'M' } },
  }
}
