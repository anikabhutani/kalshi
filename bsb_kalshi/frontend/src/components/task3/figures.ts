/** Plain Plotly charts for the Task 3 (NFL costs) page. */

import type { Data } from 'plotly.js-dist-min'
import type { T3CostRow, T3GapRow, T3Results } from '@/lib/api'
import { CHART_COLORS } from '@/lib/chartTheme'
import type { Figure } from '@/lib/figures'

export const MARKET_TYPES = ['Game winner', 'Spread', 'Total points', 'All types'] as const

export const CHECKPOINT_LABEL: Record<string, string> = {
  '24h': '24 hours before',
  '3h': '3 hours before',
  '1h': '1 hour before',
  '15m': '15 minutes before',
}

const SIZE_COLORS = [CHART_COLORS.blue, CHART_COLORS.primary, CHART_COLORS.amber]
const TYPE_COLORS: Record<string, string> = {
  'Game winner': CHART_COLORS.blue,
  Spread: CHART_COLORS.amber,
  'Total points': CHART_COLORS.pink,
  'All types': CHART_COLORS.primary,
}

const COST_AXIS = { title: { text: 'Median cost per $10 bet ($)' }, tickprefix: '$', rangemode: 'tozero' as const }

function contracts(size: number): string {
  return `${size} contract${size === 1 ? '' : 's'}`
}

function hover(r: T3CostRow): string {
  return (
    `median $${r.median.toFixed(2)} (middle half $${r.p25.toFixed(2)}–$${r.p75.toFixed(2)})<br>` +
    `gap part $${r.gap_part.toFixed(2)} + fee part $${r.fee_part.toFixed(2)}<br>` +
    `${r.cents_per_contract.toFixed(2)}¢ per contract · ${r.n.toLocaleString()} bets`
  )
}

/** Grouped bars: one bar per order size, for each value of ``key``. */
function bySize(
  rows: T3CostRow[],
  categories: string[],
  key: (r: T3CostRow) => string | undefined,
  sizes: number[],
  xTitle: string,
): Figure | null {
  if (rows.length === 0) return null
  const data: Data[] = sizes.map((size, i) => {
    const bySize = new Map(rows.filter((r) => r.size === size).map((r) => [key(r), r]))
    const present = categories.filter((c) => bySize.has(c))
    return {
      type: 'bar',
      name: contracts(size),
      x: present,
      y: present.map((c) => bySize.get(c)!.median),
      text: present.map((c) => hover(bySize.get(c)!)),
      hovertemplate: `%{x} · ${contracts(size)}<br>%{text}<extra></extra>`,
      textposition: 'none',
      marker: { color: SIZE_COLORS[i % SIZE_COLORS.length] },
    }
  })
  return {
    data,
    layout: { barmode: 'group', yaxis: COST_AXIS, xaxis: { title: { text: xTitle }, type: 'category' } },
    height: 360,
  }
}

export function priceGroupFigure(res: T3Results, checkpoint: string): Figure | null {
  const rows = res.results.by_price_group.filter((r) => r.checkpoint === checkpoint)
  return bySize(rows, res.price_groups, (r) => r.price_group, res.sizes, 'Price paid per contract')
}

export function marketTypeFigure(res: T3Results, checkpoint: string): Figure | null {
  const rows = res.results.by_market_type.filter((r) => r.checkpoint === checkpoint)
  return bySize(rows, [...MARKET_TYPES], (r) => r.market_type, res.sizes, 'Kind of bet')
}

/** One line per kind of bet across weeks, at one order size and checkpoint. */
export function weekFigure(res: T3Results, checkpoint: string, size: number): Figure | null {
  const rows = res.results.by_week.filter((r) => r.checkpoint === checkpoint && r.size === size)
  if (rows.length === 0) return null
  const weeks = [...new Set(rows.map((r) => r.week!))].sort((a, b) => a - b)
  const data: Data[] = MARKET_TYPES.map((type) => {
    const byWeek = new Map(rows.filter((r) => r.market_type === type).map((r) => [r.week!, r]))
    const present = weeks.filter((w) => byWeek.has(w))
    return {
      type: 'scatter',
      mode: 'lines+markers',
      name: type,
      x: present.map((w) => `Week ${w}`),
      y: present.map((w) => byWeek.get(w)!.median),
      text: present.map((w) => hover(byWeek.get(w)!)),
      hovertemplate: `${type} · %{x}<br>%{text}<extra></extra>`,
      line: { color: TYPE_COLORS[type], width: type === 'All types' ? 3 : 2 },
    }
  })
  return { data, layout: { yaxis: COST_AXIS, xaxis: { title: { text: 'NFL week' }, type: 'category' } }, height: 340 }
}

/** One line per kind of bet across the four checkpoints, at one order size. */
export function kickoffFigure(res: T3Results, size: number): Figure | null {
  const rows = res.results.by_market_type.filter((r) => r.size === size)
  if (rows.length === 0) return null
  const data: Data[] = MARKET_TYPES.map((type) => {
    const byCheckpoint = new Map(rows.filter((r) => r.market_type === type).map((r) => [r.checkpoint, r]))
    const present = res.checkpoints.filter((c) => byCheckpoint.has(c))
    return {
      type: 'scatter',
      mode: 'lines+markers',
      name: type,
      x: present.map((c) => CHECKPOINT_LABEL[c] ?? c),
      y: present.map((c) => byCheckpoint.get(c)!.median),
      text: present.map((c) => hover(byCheckpoint.get(c)!)),
      hovertemplate: `${type} · %{x}<br>%{text}<extra></extra>`,
      line: { color: TYPE_COLORS[type], width: type === 'All types' ? 3 : 2 },
    }
  })
  return {
    data,
    layout: { yaxis: COST_AXIS, xaxis: { title: { text: 'Time before kickoff' }, type: 'category' } },
    height: 340,
  }
}

/** Median bid-ask gap (cents) and share of quotes with a gap of 3¢ or more, by checkpoint. */
export function gapFigure(res: T3Results): Figure | null {
  if (res.gaps.length === 0) return null
  const data: Data[] = MARKET_TYPES.flatMap((type) => {
    const byCheckpoint = new Map(res.gaps.filter((g) => g.market_type === type).map((g) => [g.checkpoint, g]))
    const present = res.checkpoints.filter((c) => byCheckpoint.has(c))
    const x = present.map((c) => CHECKPOINT_LABEL[c] ?? c)
    const pick = (f: (g: T3GapRow) => number) => present.map((c) => f(byCheckpoint.get(c)!))
    return [
      {
        type: 'scatter',
        mode: 'lines+markers',
        name: `${type}: median gap`,
        legendgroup: type,
        x,
        y: pick((g) => g.median_gap_cents),
        hovertemplate: `${type} · %{x}<br>median gap %{y:.1f}¢<extra></extra>`,
        line: { color: TYPE_COLORS[type] },
      },
      {
        type: 'bar',
        name: `${type}: share ≥ 3¢`,
        legendgroup: type,
        x,
        y: pick((g) => g.wide_share * 100),
        yaxis: 'y2',
        opacity: 0.35,
        hovertemplate: `${type} · %{x}<br>%{y:.1f}% of quotes have a gap of 3¢ or more<extra></extra>`,
        marker: { color: TYPE_COLORS[type] },
      },
    ] as Data[]
  })
  return {
    data,
    layout: {
      barmode: 'group',
      yaxis: { title: { text: 'Median gap (¢)' }, ticksuffix: '¢', rangemode: 'tozero' },
      yaxis2: { title: { text: 'Quotes with a gap ≥ 3¢' }, ticksuffix: '%', overlaying: 'y', side: 'right', rangemode: 'tozero', showgrid: false },
      xaxis: { title: { text: 'Time before kickoff' }, type: 'category' },
      margin: { l: 56, r: 64, t: 16, b: 44 },
    },
    height: 360,
  }
}
