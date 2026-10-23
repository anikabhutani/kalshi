import type { Config, Layout, LayoutAxis } from 'plotly.js-dist-min'

/** Plotly styling that matches the app's dark terminal theme. */
export const CHART_COLORS = {
  primary: '#34d399',
  blue: '#60a5fa',
  amber: '#fbbf24',
  pink: '#f472b6',
  violet: '#a78bfa',
  red: '#f87171',
  muted: '#9aa0ab',
} as const

/** Unix seconds -> date string Plotly displays as-is (epoch-ms numbers would be shown in local time). */
export function plotTime(epochS: number): string {
  return new Date(epochS * 1000).toISOString().slice(0, 23).replace('T', ' ')
}

const AXIS: Partial<LayoutAxis> = {
  gridcolor: 'rgba(255,255,255,0.06)',
  linecolor: 'rgba(255,255,255,0.12)',
  zerolinecolor: 'rgba(255,255,255,0.12)',
  tickfont: { size: 11 },
  automargin: true,
}

export function themedLayout(layout: Partial<Layout>): Partial<Layout> {
  const axes = Object.fromEntries(
    Object.entries(layout)
      .filter(([key]) => /^[xy]axis\d*$/.test(key))
      .map(([key, value]) => [key, { ...AXIS, ...(value as Partial<LayoutAxis>) }]),
  )
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Inter Variable, ui-sans-serif, system-ui', color: '#c9ccd3', size: 12 },
    colorway: Object.values(CHART_COLORS),
    margin: { l: 56, r: 24, t: 16, b: 44 },
    hovermode: 'closest',
    hoverlabel: { bgcolor: '#1c1f26', bordercolor: 'rgba(255,255,255,0.15)', font: { color: '#f2f3f5' } },
    legend: { orientation: 'h', y: 1.08, x: 0, font: { size: 11 } },
    xaxis: AXIS,
    yaxis: AXIS,
    ...layout,
    ...axes,
  }
}

export function chartConfig(filename: string): Partial<Config> {
  return {
    displaylogo: false,
    responsive: true,
    toImageButtonOptions: { format: 'png', filename, scale: 2 },
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  }
}
