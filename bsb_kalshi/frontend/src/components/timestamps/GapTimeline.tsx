import { useMemo } from 'react'
import { CircleCheck } from 'lucide-react'
import type { Data } from 'plotly.js-dist-min'
import type { LabResult } from '@/lib/api'
import { CHART_COLORS, plotTime } from '@/lib/chartTheme'
import { fmtDuration } from '@/lib/format'
import { Chart } from '@/components/charts/Chart'
import { EmptyState } from '@/components/EmptyState'
import { gapSeries } from '@/components/timestamps/sources'

/** Each run of empty slots drawn as a bar from its start to its end, one row per gap analysis. */
export function GapTimeline({ result }: { result: LabResult }) {
  const series = useMemo(() => gapSeries(result), [result])
  const data = useMemo<Data[]>(
    () =>
      series.map((s) => ({
        type: 'bar',
        orientation: 'h',
        name: s.label,
        y: s.stats.runs.map(() => s.label),
        base: s.stats.runs.map((r) => plotTime(r.start_s)),
        x: s.stats.runs.map((r) => (r.end_s - r.start_s) * 1000),
        customdata: s.stats.runs.map((r) => [
          new Date(r.start_s * 1000).toISOString(),
          new Date(r.end_s * 1000).toISOString(),
          fmtDuration(r.end_s - r.start_s),
          r.slots,
        ]),
        marker: { color: s.kind === 'missing' ? CHART_COLORS.red : CHART_COLORS.amber },
        hovertemplate: '%{customdata[0]} → %{customdata[1]}<br>%{customdata[2]} (%{customdata[3]} slots)<extra>%{y}</extra>',
        showlegend: false,
      })),
    [series],
  )
  const truncated = series.filter((s) => s.stats.runs_truncated)
  if (series.every((s) => s.stats.runs.length === 0)) {
    return (
      <EmptyState icon={CircleCheck} title="No gaps in this time range">
        Checked: {series.map((s) => `${s.label} (${s.stats.expected_slots} slots)`).join(' · ')}
      </EmptyState>
    )
  }
  return (
    <div className="grid gap-2">
      <Chart
        data={data}
        filename="m3-gap-timeline"
        height={Math.max(220, series.length * 44 + 90)}
        layout={{
          barmode: 'overlay',
          xaxis: { type: 'date', title: { text: 'UTC' } },
          yaxis: {
            type: 'category',
            autorange: 'reversed',
            categoryorder: 'array',
            categoryarray: series.map((s) => s.label),
          },
          margin: { l: 230, r: 24, t: 16, b: 44 },
        }}
      />
      <p className="text-[11px] text-muted-foreground">
        Red: Kalshi had no data at all for that stretch. Amber: data was there, but nobody traded.
        {truncated.length > 0 && ` Only the 2000 longest gaps are drawn for: ${truncated.map((s) => s.label).join(', ')}.`}
      </p>
    </div>
  )
}
