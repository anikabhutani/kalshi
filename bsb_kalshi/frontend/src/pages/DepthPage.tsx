import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { History, Play, TriangleAlert } from 'lucide-react'
import { api, type DepthParams, type DepthResult, type DepthTarget } from '@/lib/api'
import { archiveMatrixFigure, depthTimelineFigure } from '@/lib/figures'
import { navItem } from '@/lib/nav'
import { fmtUtc } from '@/lib/format'
import { useGuardedRun } from '@/hooks/useGuardedRun'
import { useModuleJob } from '@/hooks/useModuleJob'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Chart } from '@/components/charts/Chart'
import { DepthTable, MatrixTable } from '@/components/depth/DepthTables'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { NativeSelect } from '@/components/NativeSelect'
import { NotesBox } from '@/components/NotesBox'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { RunConfirmDialog } from '@/components/RunConfirmDialog'

const ITEM = navItem('/depth')

function TargetPicker({
  targets,
  selected,
  onToggle,
}: {
  targets: DepthTarget[]
  selected: string[]
  onToggle: (id: string) => void
}) {
  return (
    <div className="grid gap-2 md:grid-cols-2">
      {targets.map((t) => (
        <label
          key={t.id}
          className={`flex items-start gap-2.5 rounded-lg border p-3 text-xs ${t.available ? 'cursor-pointer hover:bg-surface' : 'opacity-60'}`}
        >
          <input
            type="checkbox"
            className="mt-0.5 accent-primary"
            disabled={!t.available}
            checked={selected.includes(t.id)}
            onChange={() => onToggle(t.id)}
          />
          <span className="grid gap-0.5">
            <span className="font-medium text-foreground">{t.label}</span>
            <span className="font-mono text-muted-foreground">
              GET {t.path}
              {Object.entries(t.fixed_params).map(([k, v]) => ` ${k}=${v}`)}
            </span>
            <span className="text-muted-foreground">
              {t.mode === 'bisect'
                ? `Finds the oldest data by repeatedly halving the date range (like guessing a number between 1 and 100), using the “${t.bound_param}” date filter.`
                : `Has no date filter, so the test flips through pages (${t.page_limit ?? '?'} items each) going back in time.`}
            </span>
            {t.reason !== null && <span className="text-warning">{t.reason}</span>}
          </span>
        </label>
      ))}
    </div>
  )
}

function Results({ jobId, result }: { jobId: string; result: DepthResult }) {
  const timeline = useMemo(() => depthTimelineFigure(result), [result])
  const matrix = useMemo(() => archiveMatrixFigure(result), [result])
  const cutoff = Object.entries(result.cutoff)
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        Run at {fmtUtc(result.run_at)}
        <Badge variant="outline" className="font-mono">
          run {jobId.slice(0, 8)}
        </Badge>
        <span>
          searched back to {result.params.search_from}, accurate to 1 {result.params.resolution}, at most{' '}
          {result.params.request_cap} requests
        </span>
        {result.partial && <Badge className="bg-warning/15 text-warning">incomplete: test was stopped early</Badge>}
      </div>
      {result.notes.length > 0 && (
        <div className="grid gap-1 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-warning">
          {result.notes.map((n) => (
            <div key={n} className="flex items-center gap-2">
              <TriangleAlert className="size-3.5" /> {n}
            </div>
          ))}
        </div>
      )}

      <Section
        title="Where the archive begins"
        description="Kalshi moves older data into a separate archive. These are the dates Kalshi reported as the dividing line between live and archived data when the test ran."
      >
        {cutoff.length === 0 ? (
          <p className="text-xs text-muted-foreground">Kalshi did not return the archive dates.</p>
        ) : (
          <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
            {cutoff.map(([field, value]) => (
              <div key={field} className="contents">
                <dt className="font-mono text-muted-foreground">{field}</dt>
                <dd className="font-mono">{value.utc !== null ? fmtUtc(value.utc) : String(value.raw)}</dd>
              </div>
            ))}
          </dl>
        )}
      </Section>

      <Section
        title="How far back each kind of data goes"
        description="Green bar: the time span where we found data. Amber: the oldest data is somewhere in this range. Small ticks: each test request. Dashed lines: where the archive begins."
      >
        {timeline === null ? (
          <EmptyState icon={History} title="No data with dates was found in this run" />
        ) : (
          <Chart data={timeline.data} layout={timeline.layout} height={timeline.height} filename="m4-availability" />
        )}
      </Section>

      <Section title="Oldest and newest data found" description="One row per kind of data tested. Sort, filter, or download as a spreadsheet (CSV).">
        <DepthTable result={result} />
      </Section>

      <Section
        title="Live or archived? Where to find older bets"
        description="A few example bets, each requested from both the live system and the archive, to see which one has it. “Side of cutoff” says whether the bet finished before or after the archive dividing line."
      >
        <div className="grid gap-4">
          {matrix !== null && <Chart data={matrix.data} layout={matrix.layout} height={matrix.height} filename="m4-archive-matrix" />}
          <MatrixTable result={result} />
        </div>
      </Section>
    </>
  )
}

export function DepthPage() {
  const targetsQuery = useQuery({ queryKey: ['m4-targets'], queryFn: api.depthTargets })
  const [overrides, setOverrides] = useState<Partial<DepthParams>>({})
  const job = useModuleJob<DepthResult>('M4', 'depth_archive')
  const guarded = useGuardedRun<DepthParams>({
    plan: async (p) => (await api.depthPlan(p)).estimate,
    run: api.runDepth,
    onStarted: job.start,
  })

  const defaults = targetsQuery.data?.defaults
  const params: DepthParams | null = defaults === undefined ? null : { ...defaults, ...overrides }
  const set = (patch: Partial<DepthParams>) => setOverrides((prev) => ({ ...prev, ...patch }))
  const toggle = (id: string) => {
    if (params === null) return
    set({ targets: params.targets.includes(id) ? params.targets.filter((t) => t !== id) : [...params.targets, id] })
  }

  return (
    <PageShell item={ITEM}>
      <Section
        title="Find the oldest available data"
        description="Tick the kinds of data to test. For each one, the app searches backwards in time to find the oldest record Kalshi still returns, and checks which bets have moved to the archive. It never goes over the request limit you set."
        actions={
          <Button
            size="lg"
            disabled={params === null || params.targets.length === 0 || guarded.busy || job.running}
            onClick={() => params !== null && guarded.request(params)}
          >
            <Play /> Run depth test
          </Button>
        }
      >
        {targetsQuery.isLoading || params === null ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <div className="grid gap-4">
            <TargetPicker targets={targetsQuery.data?.targets ?? []} selected={params.targets} onToggle={toggle} />
            <div className="flex flex-wrap items-end gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="m4-series">League code (optional)</Label>
                <Input
                  id="m4-series"
                  value={params.series_ticker ?? ''}
                  onChange={(e) => set({ series_ticker: e.target.value.trim() || null })}
                  placeholder="only look at this league"
                  className="w-56 font-mono"
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="m4-market">Bet code (optional)</Label>
                <Input
                  id="m4-market"
                  value={params.market_ticker ?? ''}
                  onChange={(e) => set({ market_ticker: e.target.value.trim() || null })}
                  placeholder="only trades for this bet"
                  className="w-64 font-mono"
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="m4-from">Search back to (UTC date)</Label>
                <Input id="m4-from" type="date" value={params.search_from} onChange={(e) => set({ search_from: e.target.value })} className="w-40 font-mono" />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="m4-res">Accurate to</Label>
                <NativeSelect id="m4-res" value={params.resolution} onChange={(e) => set({ resolution: e.target.value as DepthParams['resolution'] })} className="w-28">
                  <option value="day">1 day</option>
                  <option value="hour">1 hour</option>
                </NativeSelect>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="m4-pages">Max pages to flip</Label>
                <Input
                  id="m4-pages"
                  type="number"
                  min={1}
                  max={20}
                  value={params.walk_page_cap}
                  onChange={(e) => set({ walk_page_cap: Math.min(20, Math.max(1, Number(e.target.value) || 1)) })}
                  className="w-28 font-mono"
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="m4-cap">Max requests</Label>
                <Input
                  id="m4-cap"
                  type="number"
                  min={5}
                  max={500}
                  value={params.request_cap}
                  onChange={(e) => set({ request_cap: Math.min(500, Math.max(5, Number(e.target.value) || 5)) })}
                  className="w-28 font-mono"
                />
              </div>
              <label className="flex h-9 items-center gap-2 text-sm">
                <input type="checkbox" className="accent-primary" checked={params.archive_matrix} onChange={(e) => set({ archive_matrix: e.target.checked })} />
                Also check live vs archive for example bets
              </label>
            </div>
            {targetsQuery.data?.cutoff_description && (
              <p className="max-w-4xl text-xs text-muted-foreground">
                <span className="font-medium text-foreground">What Kalshi’s docs say about the archive: </span>
                {targetsQuery.data.cutoff_description}
              </p>
            )}
            {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
          </div>
        )}
        <RunConfirmDialog
          open={guarded.dialogOpen}
          onOpenChange={(open) => !open && guarded.closeDialog()}
          title="Find the oldest available data"
          estimate={guarded.estimate}
          breakdown={[
            { label: 'Ask where the archive begins', value: guarded.estimate?.cutoff ?? 0 },
            { label: 'Date-range search requests (at most)', value: guarded.estimate?.bisect ?? 0 },
            { label: 'Page-flipping requests (at most)', value: guarded.estimate?.walk ?? 0 },
            { label: 'Live vs archive checks', value: guarded.estimate?.matrix ?? 0 },
          ]}
          notes={['Stops at the request limit; anything not reached is marked as skipped.']}
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
          <EmptyState icon={History} title="Not run yet">
            Tick the kinds of data to test, then press “Run depth test”.
          </EmptyState>
        )
      )}

      <RawRequestsDrawer module="M4" />
      <NotesBox questionId="Q3" />
    </PageShell>
  )
}
