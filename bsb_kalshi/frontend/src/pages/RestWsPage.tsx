import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Play, Radio, TriangleAlert } from 'lucide-react'
import { api, type RecorderParams, type RecorderResult, type SpecCompareRow, type WsChannel } from '@/lib/api'
import { navItem } from '@/lib/nav'
import { useGuardedRun } from '@/hooks/useGuardedRun'
import { useModuleJob } from '@/hooks/useModuleJob'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { NotesBox } from '@/components/NotesBox'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { RunConfirmDialog } from '@/components/RunConfirmDialog'
import { RecorderResults } from '@/components/restws/RecorderResults'

const ITEM = navItem('/rest-vs-ws')

const AUTH_NOTES_PRIVATE: Partial<Record<WsChannel, string>> = {
  orderbook_delta: 'Kalshi’s docs list this as a private feed (needs the account key).',
}

const SPEC_COLUMNS: Column<SpecCompareRow>[] = [
  { key: 'aspect', header: 'Topic', value: (r) => r.aspect, className: 'align-top font-medium whitespace-nowrap' },
  { key: 'rest', header: 'Checking (REST)', value: (r) => r.rest, className: 'align-top whitespace-pre-line min-w-72' },
  { key: 'websocket', header: 'Live stream (WebSocket)', value: (r) => r.websocket, className: 'align-top whitespace-pre-line min-w-72' },
  {
    key: 'source',
    header: 'Where in the docs',
    value: (r) => `REST: ${r.rest_source} · WS: ${r.ws_source}`,
    className: 'align-top whitespace-normal font-mono text-[11px] text-muted-foreground',
  },
]

const clamp = (value: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, value))

export function RestWsPage() {
  const specQuery = useQuery({ queryKey: ['m6-spec'], queryFn: api.wsSpec })
  const [params, setParams] = useState<RecorderParams>({
    market_ticker: '',
    duration_min: 5,
    poll_interval_s: 5,
    channels: ['ticker', 'trade'],
    poll_trades: true,
  })
  const job = useModuleJob<RecorderResult>('M6', 'recorder')
  const guarded = useGuardedRun<RecorderParams>({
    plan: async (p) => (await api.recorderPlan(p)).estimate,
    run: api.runRecorder,
    onStarted: job.start,
  })
  const set = (patch: Partial<RecorderParams>) => setParams((prev) => ({ ...prev, ...patch }))
  const toggleChannel = (c: WsChannel) =>
    set({ channels: params.channels.includes(c) ? params.channels.filter((x) => x !== c) : [...params.channels, c] })

  const spec = specQuery.data
  const rps = spec?.rate_limit_rps ?? null
  const neededRps = (params.poll_trades ? 2 : 1) / params.poll_interval_s
  const tooFast = rps !== null && neededRps > rps
  const blocked = spec !== undefined && (!spec.credentials_configured || spec.ws_url === null)
  const canRun = params.market_ticker.trim() !== '' && params.channels.length > 0 && !tooFast && !blocked && !guarded.busy && !job.running

  return (
    <PageShell item={ITEM}>
      <Section
        title="Record one bet both ways at once"
        description="For a few minutes, the app watches one live bet in two ways at the same time: (1) checking, which asks Kalshi for the price every few seconds, and (2) live stream, where Kalshi pushes every change to us instantly. Afterwards it compares what each one caught. Listen-only: the app can’t send anything else."
        actions={
          <Button size="lg" disabled={!canRun} onClick={() => guarded.request({ ...params, market_ticker: params.market_ticker.trim() })}>
            <Play /> Start recording
          </Button>
        }
      >
        {specQuery.isLoading || spec === undefined ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <div className="grid gap-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="m6-ticker">Bet code (must be open for betting now)</Label>
                <Input
                  id="m6-ticker"
                  value={params.market_ticker}
                  onChange={(e) => set({ market_ticker: e.target.value })}
                  placeholder="Copy one from the “How data is organized” page"
                  className="w-72 font-mono"
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="m6-duration">Record for (minutes, 1–30)</Label>
                <Input
                  id="m6-duration"
                  type="number"
                  min={1}
                  max={30}
                  value={params.duration_min}
                  onChange={(e) => set({ duration_min: clamp(Math.round(Number(e.target.value) || 1), 1, 30) })}
                  className="w-36 font-mono"
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="m6-interval">Check price every (seconds)</Label>
                <Input
                  id="m6-interval"
                  type="number"
                  min={0.5}
                  max={60}
                  step={0.5}
                  value={params.poll_interval_s}
                  onChange={(e) => set({ poll_interval_s: clamp(Number(e.target.value) || 5, 0.5, 60) })}
                  className="w-36 font-mono"
                />
              </div>
              <label className="flex h-9 items-center gap-2 text-sm">
                <input type="checkbox" className="accent-primary" checked={params.poll_trades} onChange={(e) => set({ poll_trades: e.target.checked })} />
                Also check the list of trades each time
              </label>
            </div>
            <div className="grid gap-2">
              <span className="text-xs font-medium">Which live feeds to listen to</span>
              <div className="flex flex-wrap gap-2">
                {spec.recordable_channels.map((c) => (
                  <label key={c} className="flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-xs hover:bg-surface">
                    <input type="checkbox" className="mt-0.5 accent-primary" checked={params.channels.includes(c)} onChange={() => toggleChannel(c)} />
                    <span className="grid gap-0.5">
                      <span className="font-mono text-foreground">{c}</span>
                      <span className="text-muted-foreground">{spec.channels.find((x) => x.name === c)?.title ?? ''}</span>
                      {AUTH_NOTES_PRIVATE[c] !== undefined && <span className="text-warning">{AUTH_NOTES_PRIVATE[c]}</span>}
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Live stream address: <span className="font-mono text-foreground">{spec.ws_url ?? 'none'}</span>. Connecting to the stream is
              saved as a receipt like any other request. Checking at this pace needs {neededRps.toFixed(2)} requests per second; this
              app’s limit is {rps}.
            </p>
            {!spec.credentials_configured && (
              <p className="flex items-center gap-1.5 text-xs text-warning">
                <TriangleAlert className="size-3.5" /> No account key is set up. Kalshi requires one for the live stream.
              </p>
            )}
            {spec.ws_url === null && (
              <p className="flex items-center gap-1.5 text-xs text-warning">
                <TriangleAlert className="size-3.5" /> Kalshi’s docs don’t list a live stream address for this server.
              </p>
            )}
            {tooFast && (
              <p className="flex items-center gap-1.5 text-xs text-warning">
                <TriangleAlert className="size-3.5" /> Checking this often would go over the speed limit. Check less often, or untick the trades box.
              </p>
            )}
            {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
          </div>
        )}
        <RunConfirmDialog
          open={guarded.dialogOpen}
          onOpenChange={(open) => !open && guarded.closeDialog()}
          title="Start recording"
          estimate={guarded.estimate}
          breakdown={[
            { label: 'Price checks', value: guarded.estimate?.rest_cycles ?? 0 },
            { label: 'Requests for those checks', value: guarded.estimate?.rest_requests ?? 0 },
            { label: 'Live stream connections (at most)', value: guarded.estimate?.ws_requests_max ?? 0 },
          ]}
          notes={[
            `Records ${params.market_ticker.trim() || '–'} for ${params.duration_min} minute(s).`,
            'The live stream only listens. If the connection drops, it retries up to 6 times, waiting longer each time.',
          ]}
          fixedDurationS={params.duration_min * 60}
          onConfirm={guarded.confirm}
          confirming={guarded.confirming}
        />
      </Section>

      {job.loading ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : job.job?.result ? (
        <RecorderResults key={job.job.id} jobId={job.job.id} result={job.job.result} />
      ) : (
        !job.running && (
          <EmptyState icon={Radio} title="No recording yet">
            Enter the code of a bet that is open right now and press “Start recording”.
          </EmptyState>
        )
      )}

      <Section
        title="What Kalshi’s docs say about each method"
        description="Side-by-side comparison using only text from Kalshi’s official documentation. If the docs don’t cover something, the cell says “Not stated in the specs.”"
      >
        {spec === undefined ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <div className="grid gap-4">
            <DataTable columns={SPEC_COLUMNS} rows={spec.rows} rowKey={(r) => r.aspect} csvName="m6-spec-comparison.csv" empty="No rows." maxHeight="max-h-[40rem]" />
            <p className="text-xs text-muted-foreground">
              Live stream docs version {spec.asyncapi_version}. Live feeds Kalshi offers: {spec.channels.map((c) => c.name).join(', ')}.
            </p>
          </div>
        )}
      </Section>

      <RawRequestsDrawer module="M6" />
      <NotesBox questionId="Q6" />
    </PageShell>
  )
}
