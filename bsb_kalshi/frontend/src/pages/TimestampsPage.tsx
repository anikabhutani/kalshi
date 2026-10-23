import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Clock, Play, Search, TriangleAlert } from 'lucide-react'
import { api, type LabParams, type LabResult, type LoadedMarket } from '@/lib/api'
import { navItem } from '@/lib/nav'
import { fmtUtc, fromUtcInput, toUtcInput } from '@/lib/format'
import { useGuardedRun } from '@/hooks/useGuardedRun'
import { useModuleJob } from '@/hooks/useModuleJob'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { NativeSelect } from '@/components/NativeSelect'
import { NotesBox } from '@/components/NotesBox'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { RunConfirmDialog } from '@/components/RunConfirmDialog'
import { DensityHeatmap } from '@/components/timestamps/DensityHeatmap'
import { GapTimeline } from '@/components/timestamps/GapTimeline'
import { ClockPanel, MetadataTable, MetricsTable } from '@/components/timestamps/LabTables'
import { PriceAtWidget } from '@/components/timestamps/PriceAtWidget'
import { PriceChart } from '@/components/timestamps/PriceChart'

const ITEM = navItem('/timestamps')
const BUCKETS = [1, 10, 60, 300, 900, 3600]

function MarketCard({ loaded }: { loaded: LoadedMarket }) {
  const m = loaded.market
  const rows: [string, string | null][] = [
    ['Betting opened', m.open_time],
    ['Game time', m.occurrence_datetime],
    ['Betting closed', m.close_time],
    ['Expected to end', m.expected_expiration_time],
    ['Paid out', m.settlement_ts],
  ]
  return (
    <div className="grid gap-3 rounded-lg border bg-surface p-4 md:grid-cols-[1fr_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm">{m.ticker}</span>
          <Badge variant="outline" className="font-mono">
            {m.status ?? '–'}
          </Badge>
          <Badge className={loaded.archived ? 'bg-warning/15 text-warning' : 'bg-primary/15 text-primary'}>
            {loaded.archived ? 'Archived (older data store)' : 'Live data'}
          </Badge>
          <Badge variant="secondary">details from {loaded.source}</Badge>
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          {m.title}
          {m.yes_sub_title && ` · “Yes” means: ${m.yes_sub_title}`} · league{' '}
          <span className="font-mono">{loaded.series_ticker ?? 'unknown'}</span>
        </div>
      </div>
      <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-mono">{fmtUtc(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function Results({ jobId, result }: { jobId: string; result: LabResult }) {
  const [markerTs, setMarkerTs] = useState<number | null>(null)
  const { params } = result
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        Showing results for <span className="font-mono text-foreground">{params.market_ticker}</span>
        <span>
          from {fmtUtc(params.start_ts)} to {fmtUtc(params.end_ts)}
        </span>
        <Badge variant="outline" className="font-mono">
          run {jobId.slice(0, 8)}
        </Badge>
        {result.candle_endpoint && (
          <Badge variant="secondary" className="font-mono" title="Address used for price history">
            {result.candle_endpoint}
          </Badge>
        )}
        {result.partial && <Badge className="bg-warning/15 text-warning">incomplete: test was stopped early</Badge>}
      </div>
      {result.errors.length > 0 && (
        <div className="grid gap-1 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs">
          {result.errors.map((e) => (
            <div key={`${e.source}-${e.request_id}`} className="flex items-center gap-2 text-warning">
              <TriangleAlert className="size-3.5" /> {e.source}: {e.message}{' '}
              <span className="font-mono text-muted-foreground">request #{e.request_id}</span>
            </div>
          ))}
        </div>
      )}

      <Section
        title="How complete is each price source?"
        description="Kalshi gives prices in several ways: per-minute/hour/day summaries (candles), individual trades, and the current order book. This table counts how many data points each one has, how far apart they are, and how many slots are empty. Δ means the time between one data point and the next."
      >
        <MetricsTable result={result} />
      </Section>

      <Section
        title="Price over time"
        description="Each line is a different price source for the same bet. Drag to zoom in, double-click to reset, camera icon to save a picture."
      >
        <PriceChart result={result} markerTs={markerTs} />
      </Section>

      <Section
        title="What was the price at a specific moment?"
        description="Pick a time and see what each source says the price was then. They don’t always agree."
      >
        <PriceAtWidget jobId={jobId} result={result} onQuery={setMarkerTs} />
      </Section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title="When was there data?" description="Darker squares mean more data points in that time slot (UTC).">
          <DensityHeatmap result={result} />
        </Section>
        <Section title="Gaps with no data" description="Stretches of time where a source had nothing at all.">
          <GapTimeline result={result} />
        </Section>
      </div>

      <Section
        title="Are the clocks in sync?"
        description="Every reply from Kalshi carries Kalshi’s own clock time. We compare it with our computer’s clock, and also show how long each reply took."
      >
        <ClockPanel rows={result.clock.rows} summary={result.clock.summary} />
      </Section>

      {result.metadata_timestamps !== undefined && (
        <Section title="Key dates on this bet" description="Every date/time field Kalshi lists for this bet, and the format it uses.">
          <MetadataTable rows={result.metadata_timestamps} />
        </Section>
      )}
    </>
  )
}

export function TimestampsPage() {
  const [search] = useSearchParams()
  const [ticker, setTicker] = useState(search.get('market') ?? '')
  const [loaded, setLoaded] = useState<LoadedMarket | null>(null)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [pageCap, setPageCap] = useState(10)
  const [bucket, setBucket] = useState(60)
  const job = useModuleJob<LabResult>('M3', 'price_sources')
  const guarded = useGuardedRun<LabParams>({
    plan: async (p) => (await api.labPlan(p)).estimate,
    run: api.runLab,
    onStarted: job.start,
  })

  const load = useMutation({
    mutationFn: () => api.loadMarket(ticker),
    onSuccess: (res) => {
      setLoaded(res)
      setStart(toUtcInput(res.suggested_window.start_ts))
      setEnd(toUtcInput(res.suggested_window.end_ts))
    },
  })
  const { mutate: loadMarket } = load
  const linkedMarket = search.get('market')
  const autoLoaded = useRef<string | null>(null)
  useEffect(() => {
    if (linkedMarket === null || linkedMarket === '' || autoLoaded.current === linkedMarket) return
    autoLoaded.current = linkedMarket
    loadMarket()
  }, [linkedMarket, loadMarket])

  const startTs = fromUtcInput(start)
  const endTs = fromUtcInput(end)
  const windowValid = startTs !== null && endTs !== null && endTs > startTs
  const setWindow = (from: number, to: number) => {
    setStart(toUtcInput(from))
    setEnd(toUtcInput(to))
  }
  const runParams = (): LabParams | null =>
    loaded === null || !windowValid
      ? null
      : {
          market_ticker: loaded.market.ticker,
          series_ticker: loaded.series_ticker ?? search.get('series'),
          start_ts: startTs,
          end_ts: endTs,
          trade_page_cap: pageCap,
          trade_bucket_s: bucket,
          archived: loaded.archived,
        }

  return (
    <PageShell item={ITEM}>
      <Section
        title="Choose a bet and a time range"
        description="Enter a bet’s code and press “Load bet” (3–4 requests). Then pick a time range and run the test: it downloads the price history at every available detail level (per minute, hour and day), every trade, and the current order book."
        actions={
          <div className="flex flex-col items-end gap-1">
            <Button
              size="lg"
              disabled={runParams() === null || guarded.busy || job.running}
              onClick={() => {
                const p = runParams()
                if (p !== null) guarded.request(p)
              }}
            >
              <Play /> Run price test
            </Button>
            {loaded === null && (
              <span className="text-[11px] text-muted-foreground">Load a bet first.</span>
            )}
          </div>
        }
      >
        <div className="grid gap-4">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (ticker !== '') load.mutate()
            }}
          >
            <div className="grid min-w-72 flex-1 gap-1.5">
              <Label htmlFor="m3-ticker">Bet code (market ticker)</Label>
              <Input
                id="m3-ticker"
                value={ticker}
                onChange={(e) => {
                  const next = e.target.value.trim()
                  setTicker(next)
                  if (loaded !== null && loaded.market.ticker !== next) setLoaded(null)
                }}
                placeholder="Copy one from the “How data is organized” page"
                className="font-mono"
              />
            </div>
            <Button type="submit" variant="outline" disabled={ticker === '' || load.isPending}>
              <Search /> Load bet
            </Button>
          </form>

          {load.isPending && <Skeleton className="h-24 w-full" />}
          {loaded !== null && <MarketCard loaded={loaded} />}

          {loaded !== null && (
            <div className="grid gap-3 rounded-lg border p-4">
              <div className="flex flex-wrap items-end gap-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="m3-start">Start (UTC)</Label>
                  <Input id="m3-start" type="datetime-local" step={1} value={start} onChange={(e) => setStart(e.target.value)} className="w-56 font-mono" />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="m3-end">End (UTC)</Label>
                  <Input id="m3-end" type="datetime-local" step={1} value={end} onChange={(e) => setEnd(e.target.value)} className="w-56 font-mono" />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="m3-cap">Max pages of trades</Label>
                  <Input
                    id="m3-cap"
                    type="number"
                    min={1}
                    max={100}
                    value={pageCap}
                    onChange={(e) => setPageCap(Math.min(100, Math.max(1, Number(e.target.value) || 1)))}
                    className="w-28 font-mono"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="m3-bucket">Count trade gaps per</Label>
                  <NativeSelect id="m3-bucket" value={bucket} onChange={(e) => setBucket(Number(e.target.value))} className="w-28">
                    {BUCKETS.map((b) => (
                      <option key={b} value={b}>
                        {b < 60 ? `${b} s` : `${b / 60} min`}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-muted-foreground">Quick windows:</span>
                <Button size="xs" variant="outline" onClick={() => setWindow(loaded.suggested_window.start_ts, loaded.suggested_window.end_ts)}>
                  Open → close (or now)
                </Button>
                {[6, 24].map((h) => (
                  <Button
                    key={h}
                    size="xs"
                    variant="outline"
                    onClick={() => setWindow(loaded.suggested_window.end_ts - h * 3600, loaded.suggested_window.end_ts)}
                  >
                    Last {h}h before close
                  </Button>
                ))}
                {!windowValid && <span className="text-destructive">End must be after start.</span>}
              </div>
            </div>
          )}

          {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
        </div>
        <RunConfirmDialog
          open={guarded.dialogOpen}
          onOpenChange={(open) => !open && guarded.closeDialog()}
          title="Run price test"
          estimate={guarded.estimate}
          breakdown={[
            { label: 'Bet details and order book', value: guarded.estimate?.fixed ?? 0 },
            { label: 'Price history (all detail levels)', value: guarded.estimate?.candles ?? 0 },
            { label: 'Pages of trades (at most)', value: guarded.estimate?.trades_max ?? 0 },
          ]}
          notes={['Stops fetching trades early once there are no more pages.']}
          onConfirm={guarded.confirm}
          confirming={guarded.confirming}
        />
      </Section>

      {job.loading ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : job.job?.result ? (
        <Results key={job.job.id} jobId={job.job.id} result={job.job.result} />
      ) : (
        !job.running && (
          <EmptyState icon={Clock} title="No price test run yet">
            Load a bet, choose a time range, then press “Run price test”.
          </EmptyState>
        )
      )}

      <RawRequestsDrawer module="M3" />
      <NotesBox questionId="Q2" />
    </PageShell>
  )
}
