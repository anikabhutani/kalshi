import { useMemo, useState } from 'react'
import type { Data } from 'plotly.js-dist-min'
import type { LabResult } from '@/lib/api'
import { NativeSelect } from '@/components/NativeSelect'
import { Chart } from '@/components/charts/Chart'
import { candleLabel, candleSources, tradeSource } from '@/components/timestamps/sources'

type Mode = 'hour-minute' | 'day-hour'
const TWO_DAYS_S = 2 * 86_400

const range = (n: number) => Array.from({ length: n }, (_, i) => i)
const pad = (n: number) => String(n).padStart(2, '0')

function grid(ts: number[], mode: Mode) {
  if (mode === 'hour-minute') {
    const z = range(24).map(() => range(60).map(() => 0))
    for (const t of ts) {
      const d = new Date(t * 1000)
      z[d.getUTCHours()]![d.getUTCMinutes()]! += 1
    }
    return { x: range(60), y: range(24).map((h) => `${pad(h)}:00`), z, xTitle: 'Minute (UTC)', yTitle: 'Hour (UTC)' }
  }
  const days = [...new Set(ts.map((t) => new Date(t * 1000).toISOString().slice(0, 10)))].sort()
  const index = new Map(days.map((d, i) => [d, i]))
  const z = days.map(() => range(24).map(() => 0))
  for (const t of ts) {
    const d = new Date(t * 1000)
    z[index.get(d.toISOString().slice(0, 10))!]![d.getUTCHours()]! += 1
  }
  return { x: range(24), y: days, z, xTitle: 'Hour (UTC)', yTitle: 'Day (UTC)' }
}

/** Record counts per time cell, to show where each source has data. */
export function DensityHeatmap({ result }: { result: LabResult }) {
  const options = useMemo(() => {
    const opts: { key: string; label: string; ts: number[] }[] = []
    const trades = tradeSource(result)
    if (trades !== null) opts.push({ key: 'trades', label: 'Trades', ts: trades.rows.map((r) => r.ts) })
    for (const c of candleSources(result)) {
      opts.push({
        key: `candles_${c.interval_min}`,
        label: `${candleLabel(c.interval_min)} with a trade`,
        ts: c.rows.filter((r) => r.close !== null).map((r) => r.ts),
      })
    }
    return opts
  }, [result])
  const [sourceKey, setSourceKey] = useState(options[0]?.key ?? '')
  const source = options.find((o) => o.key === sourceKey) ?? options[0]
  const span = useMemo(() => {
    const ts = source?.ts ?? []
    return ts.length > 0 ? ts.reduce((a, b) => Math.max(a, b)) - ts.reduce((a, b) => Math.min(a, b)) : 0
  }, [source])
  const [modeChoice, setModeChoice] = useState<Mode | 'auto'>('auto')
  const mode: Mode = modeChoice === 'auto' ? (span <= TWO_DAYS_S ? 'hour-minute' : 'day-hour') : modeChoice

  const { data, xTitle, yTitle, rows } = useMemo(() => {
    const g = grid(source?.ts ?? [], mode)
    const trace: Data = {
      type: 'heatmap',
      x: g.x,
      y: g.y,
      z: g.z,
      colorscale: [
        [0, 'rgba(255,255,255,0.03)'],
        [0.0001, 'rgba(52,211,153,0.15)'],
        [1, 'rgba(52,211,153,1)'],
      ],
      xgap: 1,
      ygap: 1,
      hovertemplate: `${g.yTitle}: %{y}<br>${g.xTitle}: %{x}<br>%{z} records<extra></extra>`,
      colorbar: { thickness: 10, title: { text: 'records' } },
    }
    return { data: [trace], xTitle: g.xTitle, yTitle: g.yTitle, rows: g.y.length }
  }, [source, mode])

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <NativeSelect aria-label="Source" value={source?.key ?? ''} onChange={(e) => setSourceKey(e.target.value)} className="h-7 w-52 text-xs">
          {options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label} ({o.ts.length})
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          aria-label="Grid"
          value={modeChoice}
          onChange={(e) => setModeChoice(e.target.value as Mode | 'auto')}
          className="h-7 w-52 text-xs"
        >
          <option value="auto">Auto ({span <= TWO_DAYS_S ? 'hour × minute' : 'day × hour'})</option>
          <option value="hour-minute">Hour × minute (all days summed)</option>
          <option value="day-hour">Day × hour</option>
        </NativeSelect>
      </div>
      <Chart
        data={data}
        filename="m3-data-density"
        height={Math.min(640, Math.max(260, rows * 18 + 90))}
        layout={{
          xaxis: { title: { text: xTitle }, showgrid: false },
          yaxis: { title: { text: yTitle }, showgrid: false, autorange: 'reversed', type: 'category' },
        }}
      />
    </div>
  )
}
