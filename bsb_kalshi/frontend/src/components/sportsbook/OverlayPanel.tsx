import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Layers, TriangleAlert } from 'lucide-react'
import { api, type DatasetSummary, type Job, type OverlayBookSummary, type OverlayResult, type OverlayRow } from '@/lib/api'
import { fmtNum, fmtUtc } from '@/lib/format'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Chart } from '@/components/charts/Chart'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { NativeSelect } from '@/components/NativeSelect'
import { DummyBadge } from '@/components/sportsbook/DatasetsPanel'
import { labRunLabel } from '@/components/sportsbook/labRuns'
import { gapFigure, overlayFigure } from '@/components/sportsbook/overlayFigures'

const prob = (v: number | null) => (v === null ? null : Number(v.toFixed(4)))
const pp = (v: number | null) => (v === null ? null : Number(v.toFixed(2)))

const ROW_COLUMNS: Column<OverlayRow>[] = [
  { key: 'ts', header: 'Time', value: (r) => fmtUtc(r.timestamp_utc), className: 'font-mono' },
  { key: 'book', header: 'Sportsbook', value: (r) => r.book },
  { key: 'implied', header: 'Sportsbook chance (with margin)', value: (r) => prob(r.implied_prob), className: 'text-right tabular-nums' },
  { key: 'novig', header: 'Sportsbook chance (fair)', value: (r) => prob(r.no_vig_prob), className: 'text-right tabular-nums' },
  { key: 'kalshi', header: 'Kalshi price', value: (r) => r.kalshi_price, className: 'text-right tabular-nums' },
  { key: 'kalshi_ts', header: 'When Kalshi price was set', value: (r) => fmtUtc(r.kalshi_price_ts), className: 'font-mono' },
  { key: 'age', header: 'Kalshi price age (s)', value: (r) => (r.staleness_s === null ? null : Math.round(r.staleness_s)), className: 'text-right tabular-nums' },
  { key: 'fresh', header: 'Fresh enough?', value: (r) => (r.within_staleness ? 'yes' : 'no') },
  { key: 'gap', header: 'Difference vs fair (points)', value: (r) => pp(r.gap_no_vig_pp), className: 'text-right tabular-nums' },
  { key: 'gap_raw', header: 'Difference vs with-margin (points)', value: (r) => pp(r.gap_implied_pp), className: 'text-right tabular-nums' },
  { key: 'event', header: 'Event', value: (r) => r.event, csvOnly: true },
  { key: 'market', header: 'Outcome', value: (r) => r.market, csvOnly: true },
]

const SUMMARY_COLUMNS: Column<OverlayBookSummary>[] = [
  { key: 'book', header: 'Sportsbook', value: (s) => s.book },
  { key: 'rows', header: 'Rows', value: (s) => s.rows, className: 'text-right tabular-nums' },
  { key: 'priced', header: 'With a Kalshi price', value: (s) => s.with_kalshi_price, className: 'text-right tabular-nums' },
  { key: 'fresh', header: 'Fresh enough', value: (s) => s.within_staleness, className: 'text-right tabular-nums' },
  { key: 'mean_abs', header: 'Average size of difference', value: (s) => pp(s.mean_abs_gap_no_vig_pp), className: 'text-right tabular-nums' },
  { key: 'median', header: 'Typical difference', value: (s) => pp(s.gap_no_vig_pp.median), className: 'text-right tabular-nums' },
  { key: 'min', header: 'Smallest', value: (s) => pp(s.gap_no_vig_pp.min), className: 'text-right tabular-nums' },
  { key: 'max', header: 'Largest', value: (s) => pp(s.gap_no_vig_pp.max), className: 'text-right tabular-nums' },
  { key: 'median_raw', header: 'Typical difference vs with-margin', value: (s) => pp(s.gap_implied_pp.median), className: 'text-right tabular-nums' },
]

function OverlayResults({ result }: { result: OverlayResult }) {
  const overlay = useMemo(() => overlayFigure(result), [result])
  const gaps = useMemo(() => gapFigure(result), [result])
  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {result.is_dummy && <DummyBadge />}
        <span className="font-medium text-foreground">{result.dataset.name}</span>
        <span>
          outcome <span className="font-mono text-foreground">{result.params.selection}</span> vs Kalshi{' '}
          <span className="font-mono text-foreground">{result.market_ticker}</span> {result.series.label}
        </span>
        <span>· Kalshi price must be under {fmtNum(result.params.max_staleness_s)} s old</span>
      </div>
      {result.is_dummy && (
        <p className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs font-medium text-warning">
          <TriangleAlert className="size-4" /> DUMMY DATA: the sportsbook numbers are made up for testing, not real odds.
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        {result.series.note} Kalshi chance = “Yes” price ÷ $1.00 payout (fees not included).
      </p>
      {overlay !== null && <Chart data={overlay.data} layout={overlay.layout} height={overlay.height} filename={result.is_dummy ? 'm7-overlay-dummy' : 'm7-overlay'} />}
      <div className="grid gap-1">
        <h3 className="text-xs font-semibold">How far apart they were (Kalshi minus sportsbook fair chance, in percentage points)</h3>
        {gaps !== null ? (
          <Chart data={gaps.data} layout={gaps.layout} height={gaps.height} filename={result.is_dummy ? 'm7-gaps-dummy' : 'm7-gaps'} />
        ) : (
          <p className="text-xs text-muted-foreground">No moment had both a sportsbook fair chance and a fresh-enough Kalshi price.</p>
        )}
      </div>
      <DataTable columns={SUMMARY_COLUMNS} rows={result.summary} rowKey={(s) => s.book} csvName={result.is_dummy ? 'm7-summary-DUMMY.csv' : 'm7-summary.csv'} empty="No rows." />
      <DataTable columns={ROW_COLUMNS} rows={result.rows} rowKey={(r) => `${r.ts}-${r.book}`} csvName={result.is_dummy ? 'm7-matched-DUMMY.csv' : 'm7-matched.csv'} empty="No rows." />
    </div>
  )
}

export function OverlayPanel({ datasets, labJobs }: { datasets: DatasetSummary[]; labJobs: Job<null>[] }) {
  const [datasetId, setDatasetId] = useState('')
  const [labJobId, setLabJobId] = useState('')
  const [seriesId, setSeriesId] = useState('')
  const [selection, setSelection] = useState('')
  const [staleness, setStaleness] = useState(300)

  const dataset = datasets.find((d) => d.id === datasetId) ?? datasets[0]
  const lab = labJobId || dataset?.source_job_id || labJobs[0]?.id || ''
  const seriesQuery = useQuery({ queryKey: ['m7-series', lab], queryFn: () => api.labSeries(lab), enabled: lab !== '' })
  const series = seriesQuery.data?.series ?? []
  const seriesChoice = series.some((s) => s.id === seriesId && s.points > 0) ? seriesId : (series.find((s) => s.points > 0)?.id ?? '')
  const markets = dataset?.markets ?? []
  const outcome = markets.includes(selection) ? selection : (markets.find((m) => /\byes\b/i.test(m)) ?? markets[0] ?? '')

  const compute = useMutation({
    mutationFn: () =>
      api.overlay({ dataset_id: dataset?.id ?? '', lab_job_id: lab, selection: outcome, series_id: seriesChoice, max_staleness_s: staleness }),
  })
  const ready = dataset !== undefined && lab !== '' && seriesChoice !== '' && outcome !== ''

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="m7-dataset">Sportsbook odds file</Label>
          <NativeSelect id="m7-dataset" value={dataset?.id ?? ''} onChange={(e) => setDatasetId(e.target.value)} className="w-72" disabled={datasets.length === 0}>
            {datasets.length === 0 && <option value="">None yet (see step 1)</option>}
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.is_dummy ? '[DUMMY DATA] ' : ''}
                {d.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="m7-outcome">Outcome</Label>
          <NativeSelect id="m7-outcome" value={outcome} onChange={(e) => setSelection(e.target.value)} className="w-56" disabled={dataset === undefined}>
            {markets.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="m7-lab">Kalshi prices from price test</Label>
          <NativeSelect id="m7-lab" value={lab} onChange={(e) => setLabJobId(e.target.value)} className="w-80" disabled={labJobs.length === 0}>
            {labJobs.length === 0 && <option value="">None yet: run a price test on “Price history & timing” first</option>}
            {labJobs.map((j) => (
              <option key={j.id} value={j.id}>
                {labRunLabel(j)}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="m7-series">Which Kalshi price</Label>
          <NativeSelect id="m7-series" value={seriesChoice} onChange={(e) => setSeriesId(e.target.value)} className="w-72" disabled={series.length === 0}>
            {series.map((s) => (
              <option key={s.id} value={s.id} disabled={s.points === 0}>
                {s.label} ({s.points} pts)
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="m7-stale">Ignore Kalshi prices older than (s)</Label>
          <Input
            id="m7-stale"
            type="number"
            min={1}
            value={staleness}
            onChange={(e) => setStaleness(Math.max(1, Number(e.target.value) || 1))}
            className="w-32 font-mono"
          />
        </div>
        <Button size="lg" disabled={!ready || compute.isPending} onClick={() => compute.mutate()}>
          <Layers /> Compare
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        For each sportsbook line, the app looks up the most recent Kalshi price at that moment. If that Kalshi price is older than the limit, the
        difference is skipped rather than compared against stale data. Everything is calculated on this computer; no requests are sent.
      </p>
      {compute.data ? (
        <OverlayResults key={`${compute.data.params.dataset_id}-${compute.data.params.series_id}-${compute.data.params.selection}`} result={compute.data} />
      ) : (
        <EmptyState icon={Layers} title="Nothing compared yet">
          Choose an odds file, an outcome and a Kalshi price, then press “Compare”.
        </EmptyState>
      )}
    </div>
  )
}
