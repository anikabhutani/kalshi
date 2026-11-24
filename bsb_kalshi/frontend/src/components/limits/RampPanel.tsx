import { useMemo, useState } from 'react'
import { Activity, Play, TriangleAlert } from 'lucide-react'
import { api, type RampParams, type RampResult, type RampStep, type RateDoc } from '@/lib/api'
import { headerValuesFigure, latencyVsRateFigure, rampTimelineFigure } from '@/lib/figures'
import { useGuardedRun } from '@/hooks/useGuardedRun'
import type { ModuleJob } from '@/hooks/useModuleJob'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Chart } from '@/components/charts/Chart'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { NativeSelect } from '@/components/NativeSelect'
import { RunConfirmDialog } from '@/components/RunConfirmDialog'

const STEP_COLUMNS: Column<RampStep>[] = [
  { key: 'target', header: 'Aimed for (req/s)', value: (s) => s.target_rps, className: 'text-right tabular-nums' },
  { key: 'achieved', header: 'Actually sent (req/s)', value: (s) => s.achieved_rps, className: 'text-right tabular-nums' },
  { key: 'n', header: 'Requests', value: (s) => s.requests, className: 'text-right tabular-nums' },
  { key: 'p50', header: 'Typical reply (ms)', value: (s) => s.latency_median_ms, className: 'text-right tabular-nums' },
  { key: 'p95', header: 'Slowest 5% (ms)', value: (s) => s.latency_p95_ms, className: 'text-right tabular-nums' },
  { key: 'max', header: 'Slowest (ms)', value: (s) => s.latency_max_ms, className: 'text-right tabular-nums' },
  {
    key: 'status',
    header: 'Result codes',
    value: (s) => Object.entries(s.status_counts).map(([k, v]) => `${k}×${v}`).join(' '),
    className: 'font-mono',
  },
  { key: '429', header: '“Slow down” replies', value: (s) => s.rate_limited, className: 'text-right tabular-nums' },
]

function RampResults({ result }: { result: RampResult }) {
  const latency = useMemo(() => latencyVsRateFigure(result), [result])
  const timeline = useMemo(() => rampTimelineFigure(result), [result])
  const headers = useMemo(() => headerValuesFigure(result), [result])
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-mono text-foreground">GET {result.params.path}</span>
        <span>
          {result.requests.length} requests · our speed limit {result.limiter.rate_limit_rps} req/s
        </span>
        {result.other_running_jobs_at_start > 0 && (
          <Badge className="bg-warning/15 text-warning">{result.other_running_jobs_at_start} other test(s) were running at the same time</Badge>
        )}
        {result.first_429 ? (
          <Badge className="bg-destructive/15 text-destructive">
            Kalshi said “slow down” at {result.first_429.target_rps} req/s, so we stopped
          </Badge>
        ) : (
          <Badge variant="secondary">Kalshi never said “slow down”</Badge>
        )}
        {result.partial && <Badge className="bg-warning/15 text-warning">incomplete: test was stopped early</Badge>}
      </div>
      <DataTable columns={STEP_COLUMNS} rows={result.steps} rowKey={(s) => s.target_rps} csvName="m5-ramp-steps.csv" empty="No steps completed." />
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="grid gap-1">
          <h3 className="text-xs font-semibold">Does Kalshi slow down when we go faster?</h3>
          {latency ? <Chart data={latency.data} layout={latency.layout} height={latency.height} filename="m5-latency-vs-rate" /> : <p className="text-xs text-muted-foreground">No latencies recorded.</p>}
        </div>
        <div className="grid gap-1">
          <h3 className="text-xs font-semibold">Reply time for each request, in order</h3>
          {timeline ? <Chart data={timeline.data} layout={timeline.layout} height={timeline.height} filename="m5-ramp-timeline" /> : <p className="text-xs text-muted-foreground">No requests recorded.</p>}
        </div>
      </div>
      <div className="grid gap-1">
        <h3 className="text-xs font-semibold">Remaining budget reported by Kalshi</h3>
        {headers ? (
          <Chart data={headers.data} layout={headers.layout} height={headers.height} filename="m5-header-values" />
        ) : (
          <EmptyState icon={Activity} title="Kalshi did not report how much budget was left">
            Extra labels Kalshi attached to its replies: <span className="font-mono">{(result.header_names_seen ?? []).join(', ') || 'none'}</span>
          </EmptyState>
        )}
      </div>
    </div>
  )
}

export function RampPanel({ doc, job }: { doc: RateDoc; job: ModuleJob<RampResult> }) {
  const limit = doc.client_limiter.rate_limit_rps
  const [params, setParams] = useState<RampParams>({
    path: doc.ramp_choices.includes('/exchange/status') ? '/exchange/status' : (doc.ramp_choices[0] ?? ''),
    auth: false,
    start_rps: Math.min(1, limit),
    step_rps: 0.5,
    max_rps: limit,
    requests_per_step: 10,
  })
  const guarded = useGuardedRun<RampParams>({
    plan: async (p) => (await api.rampPlan(p)).estimate,
    run: api.runRamp,
    onStarted: job.start,
  })
  const set = (patch: Partial<RampParams>) => setParams((prev) => ({ ...prev, ...patch }))
  const num = (value: string, fallback: number) => (Number.isFinite(Number(value)) && value !== '' ? Number(value) : fallback)
  const overLimit = params.max_rps > limit

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="m5-path">Address to test</Label>
          <NativeSelect id="m5-path" value={params.path} onChange={(e) => set({ path: e.target.value })} className="w-64 font-mono">
            {doc.ramp_choices.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </NativeSelect>
        </div>
        {(
          [
            ['start_rps', 'Start speed (req/s)', 0.1],
            ['step_rps', 'Speed-up per step', 0.1],
            ['max_rps', 'Top speed (req/s)', 0.1],
            ['requests_per_step', 'Requests per step', 1],
          ] as const
        ).map(([key, label, stepSize]) => (
          <div key={key} className="grid gap-1.5">
            <Label htmlFor={`m5-${key}`}>{label}</Label>
            <Input
              id={`m5-${key}`}
              type="number"
              step={stepSize}
              min={stepSize}
              value={params[key]}
              onChange={(e) => set({ [key]: num(e.target.value, params[key]) })}
              className="w-28 font-mono"
            />
          </div>
        ))}
        <label className="flex h-9 items-center gap-2 text-sm" title={doc.credentials_configured ? undefined : 'No account key set up'}>
          <input type="checkbox" className="accent-primary" checked={params.auth} disabled={!doc.credentials_configured} onChange={(e) => set({ auth: e.target.checked })} />
          Use account key
        </label>
        <Button size="lg" className="ml-auto" disabled={guarded.busy || job.running || overLimit || params.path === ''} onClick={() => guarded.request(params)}>
          <Play /> Run speed test
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        The speed can never go above this app’s own limit ({limit} requests per second, set in Settings), and the test never sends
        more than 200 requests. It stops immediately if Kalshi says “slow down”.
      </p>
      {overLimit && (
        <p className="flex items-center gap-1.5 text-xs text-warning">
          <TriangleAlert className="size-3.5" /> Top speed is above this app’s limit. Lower it, or raise the limit in Settings first.
        </p>
      )}
      {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
      {job.job?.result ? (
        <RampResults key={job.job.id} result={job.job.result} />
      ) : (
        !job.running && (
          <EmptyState icon={Activity} title="No speed test yet">
            Pick a simple public address and press “Run speed test”.
          </EmptyState>
        )
      )}
      <RunConfirmDialog
        open={guarded.dialogOpen}
        onOpenChange={(open) => !open && guarded.closeDialog()}
        title="Run speed test"
        estimate={guarded.estimate}
        breakdown={[
          { label: 'Speed steps', value: guarded.estimate?.steps ?? 0 },
          { label: 'Requests per step', value: guarded.estimate?.per_step ?? 0 },
        ]}
        notes={[`Asks ${params.path} ${params.auth ? 'with' : 'without'} the account key.`, 'Records reply times and anything Kalshi says about remaining budget.']}
        onConfirm={guarded.confirm}
        confirming={guarded.confirming}
      />
    </div>
  )
}
