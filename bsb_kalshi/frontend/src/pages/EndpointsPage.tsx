import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ListTree, Play, Radar } from 'lucide-react'
import { api, type CatalogEndpoint, type ProbeCall } from '@/lib/api'
import { navItem } from '@/lib/nav'
import { fmtUtc } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useGuardedRun } from '@/hooks/useGuardedRun'
import { useModuleJob } from '@/hooks/useModuleJob'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { NativeSelect } from '@/components/NativeSelect'
import { NotesBox } from '@/components/NotesBox'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { RunConfirmDialog } from '@/components/RunConfirmDialog'
import { StatTile } from '@/components/StatTile'
import { CLASSIFICATION_BADGE, observed } from '@/components/endpoints/classification'
import { ClassificationByCategory, CoverageMatrix } from '@/components/endpoints/CoverageCharts'
import { RatingEditor } from '@/components/endpoints/RatingEditor'

const ITEM = navItem('/endpoints')

const SHOW_FILTERS = {
  all: { label: 'Everything', test: () => true },
  get: { label: 'Read-only ones', test: (e: CatalogEndpoint) => e.method === 'GET' },
  probed: { label: 'Tested', test: (e: CatalogEndpoint) => e.probe !== null && observed(e) !== 'not probed' },
  mismatch: { label: 'Differs from docs', test: (e: CatalogEndpoint) => e.probe?.mismatch === true },
  unprobed: {
    label: 'Not tested yet',
    test: (e: CatalogEndpoint) => e.method === 'GET' && observed(e) === 'not probed',
  },
  rated: { label: 'Rated by me', test: (e: CatalogEndpoint) => e.user.rating !== null },
} satisfies Record<string, { label: string; test: (e: CatalogEndpoint) => boolean }>

type ShowFilter = keyof typeof SHOW_FILTERS

function callCell(call: ProbeCall | null | undefined) {
  if (call === null || call === undefined) return <span className="text-muted-foreground">–</span>
  return (
    <span className="font-mono tabular-nums" title={call.error ?? `request #${call.request_id}`}>
      {call.status ?? 'ERR'}
      <span className="text-muted-foreground"> · {call.latency_ms.toFixed(0)}ms</span>
    </span>
  )
}

const list = (values: string[]) => (values.length > 0 ? values.join(', ') : null)

const COLUMNS: Column<CatalogEndpoint>[] = [
  {
    key: 'method',
    header: 'Type (GET = read)',
    value: (e) => e.method,
    render: (e) => (
      <Badge variant={e.method === 'GET' ? 'secondary' : 'outline'} className="font-mono">
        {e.method}
      </Badge>
    ),
  },
  {
    key: 'path',
    header: 'Address',
    value: (e) => e.path,
    render: (e) => (
      <span className="block max-w-xs truncate font-mono" title={`${e.path}\n${e.summary}`}>
        {e.path}
      </span>
    ),
  },
  { key: 'category', header: 'Group', value: (e) => e.category },
  {
    key: 'summary',
    header: 'What it gives you',
    value: (e) => e.summary,
    render: (e) => (
      <span className="block max-w-56 truncate" title={e.summary}>
        {e.summary}
      </span>
    ),
  },
  { key: 'spec_auth', header: 'Docs say key needed?', value: (e) => (e.auth_required_spec ? 'yes' : 'no') },
  {
    key: 'observed',
    header: 'What we found',
    value: (e) => observed(e),
    render: (e) => (
      <Badge className={CLASSIFICATION_BADGE[observed(e)]} title={e.probe?.note}>
        {observed(e)}
      </Badge>
    ),
  },
  {
    key: 'mismatch',
    header: 'Differs from docs?',
    value: (e) => (e.probe?.mismatch === true ? 'yes' : e.probe?.mismatch === false ? 'no' : null),
    render: (e) =>
      e.probe?.mismatch === true ? (
        <Badge className="bg-warning/15 text-warning">yes</Badge>
      ) : (
        <span className="text-muted-foreground">{e.probe?.mismatch === false ? 'no' : '–'}</span>
      ),
  },
  {
    key: 'no_auth',
    header: 'Result without key',
    value: (e) => e.probe?.no_auth?.status,
    render: (e) => callCell(e.probe?.no_auth),
  },
  { key: 'auth', header: 'Result with key', value: (e) => e.probe?.auth?.status, render: (e) => callCell(e.probe?.auth) },
  { key: 'note', header: 'Test note', value: (e) => e.probe?.note, className: 'max-w-56 truncate text-muted-foreground' },
  { key: 'pagination', header: 'Page settings', value: (e) => list(e.pagination_params), className: 'font-mono' },
  { key: 'time_range', header: 'Date filters', value: (e) => list(e.time_range_params), className: 'font-mono' },
  {
    key: 'ts_fields',
    header: 'Time fields',
    value: (e) => e.timestamp_fields.length,
    render: (e) => (
      <span className="font-mono tabular-nums" title={e.timestamp_fields.join('\n')}>
        {e.timestamp_fields.length}
      </span>
    ),
  },
  { key: 'historical', header: 'Archive-related', value: (e) => list(e.historical_signals) },
  { key: 'account', header: 'About our own account?', value: (e) => (e.account_specific ? 'yes' : 'no') },
  { key: 'rating', header: 'My rating', value: (e) => e.user.rating, render: (e) => <RatingEditor endpoint={e} /> },
  { key: 'reason', header: 'My reason', value: (e) => e.user.reason, csvOnly: true },
]

function ProbePanel({ credentials }: { credentials: boolean }) {
  const [includeAccount, setIncludeAccount] = useState(false)
  const job = useModuleJob('M1', 'auth_probe')
  const guarded = useGuardedRun<boolean>({
    plan: async (include) => (await api.probePlan(include)).estimate,
    run: api.runProbe,
    onStarted: job.start,
  })
  const { data: plan } = useQuery({
    queryKey: ['probe-plan', includeAccount],
    queryFn: () => api.probePlan(includeAccount),
  })

  return (
    <Section
      title="Do we need an account key?"
      description="Asks each of Kalshi’s data addresses twice: once without our account key and once with it. Comparing the two shows which data is public and which needs a key. Read-only."
      actions={
        <Button size="lg" onClick={() => guarded.request(includeAccount)} disabled={guarded.busy || job.running}>
          <Play /> Run key test
        </Button>
      }
    >
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeAccount}
              onChange={(e) => setIncludeAccount(e.target.checked)}
              className="size-4 accent-primary"
            />
            Also test addresses about our own account (off by default)
          </label>
          {plan !== undefined && (
            <span className="text-xs text-muted-foreground">
              {plan.targets} addresses to test · {plan.skipped} skipped · about {plan.estimate.total} requests
            </span>
          )}
          {!credentials && (
            <Badge className="bg-warning/15 text-warning">No account key set up: only the without-key half will run</Badge>
          )}
        </div>
        {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
      </div>
      <RunConfirmDialog
        open={guarded.dialogOpen}
        onOpenChange={(open) => !open && guarded.closeDialog()}
        title="Run key test"
        estimate={guarded.estimate}
        breakdown={[
          { label: 'Requests to find example games and markets', value: guarded.estimate?.discovery ?? 0 },
          { label: 'Test requests (without key + with key)', value: guarded.estimate?.probes ?? 0 },
        ]}
        notes={[
          includeAccount
            ? 'Account addresses are included: they only read data about our own account; nothing is changed.'
            : 'Account addresses are left out (tick the box to include them).',
          'Never more than 150 requests per run.',
        ]}
        onConfirm={guarded.confirm}
        confirming={guarded.confirming}
      />
    </Section>
  )
}

function Coverage({ endpoints }: { endpoints: CatalogEndpoint[] }) {
  const gets = endpoints.filter((e) => e.method === 'GET')
  const count = (c: string) => gets.filter((e) => observed(e) === c).length
  const mismatches = endpoints.filter((e) => e.probe?.mismatch === true).length
  return (
    <Section
      title="Results at a glance"
      description="Just counts. “Differs from docs” means what actually happened did not match what Kalshi’s documentation says about needing a key."
    >
      <div className="grid gap-5">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <StatTile label="Addresses in Kalshi’s docs" value={endpoints.length} />
          <StatTile label="Read-only addresses" value={gets.length} />
          <StatTile label="Public (no key needed)" value={count('public')} tone="primary" />
          <StatTile label="Needs a key" value={count('key required')} />
          <StatTile label="Blocked even with key" value={count('denied even with key')} />
          <StatTile label="Unclear / error" value={count('inconclusive') + count('error')} tone="warning" />
          <StatTile label="Not tested" value={count('not probed')} />
          <StatTile label="Differs from docs" value={mismatches} tone={mismatches > 0 ? 'warning' : 'default'} />
        </div>
        <div className="grid gap-5 xl:grid-cols-2">
          <div>
            <h3 className="mb-1 text-xs font-medium text-muted-foreground">What the docs say vs what we found</h3>
            <CoverageMatrix endpoints={endpoints} />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium text-muted-foreground">What we found, by group</h3>
            <ClassificationByCategory endpoints={endpoints} />
          </div>
        </div>
      </div>
    </Section>
  )
}

function CatalogTable({ endpoints }: { endpoints: CatalogEndpoint[] }) {
  const [show, setShow] = useState<ShowFilter>('all')
  const rows = useMemo(() => endpoints.filter(SHOW_FILTERS[show].test), [endpoints, show])
  return (
    <Section
      title="Full list of data addresses"
      description="Everything listed in Kalshi’s documentation, with facts about each one. Scroll right for more. The “My rating” column is for you to score how useful each one is (for Q5); the app never rates them."
    >
      <DataTable
        columns={COLUMNS}
        rows={rows}
        rowKey={(e) => e.id}
        csvName="m1-endpoint-catalog.csv"
        maxHeight="max-h-[40rem]"
        toolbar={
          <NativeSelect
            aria-label="Show"
            value={show}
            onChange={(e) => setShow(e.target.value as ShowFilter)}
            className="w-44"
          >
            {Object.entries(SHOW_FILTERS).map(([key, f]) => (
              <option key={key} value={key}>
                {f.label}
              </option>
            ))}
          </NativeSelect>
        }
        empty={
          <EmptyState icon={ListTree} title="Nothing matches this filter">
            Choose a different filter.
          </EmptyState>
        }
      />
    </Section>
  )
}

export function EndpointsPage() {
  const { data: catalog, isLoading } = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const { data: meta } = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const probeJob = catalog?.probe_job ?? null

  return (
    <PageShell item={ITEM}>
      <ProbePanel credentials={meta?.credentials_configured ?? false} />
      {isLoading || catalog === undefined ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : (
        <>
          {probeJob === null ? (
            <EmptyState icon={Radar} title="Not tested yet">
              The list below comes from Kalshi’s documentation only. Run the key test to see what actually happens.
            </EmptyState>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              Showing results of test run <span className="font-mono">{probeJob.id.slice(0, 8)}</span>
              <span>finished {fmtUtc(probeJob.finished_at)}</span>
              <Badge className={cn(probeJob.status === 'succeeded' ? 'bg-primary/15 text-primary' : 'bg-warning/15 text-warning')}>
                {probeJob.status === 'succeeded' ? 'finished' : probeJob.status}
                {probeJob.partial && ' · partial results'}
              </Badge>
              {Object.entries(probeJob.discovered_ids).map(([kind, id]) => (
                <Badge key={kind} variant="outline" className="font-mono" title={kind}>
                  {kind}: {id}
                </Badge>
              ))}
            </div>
          )}
          <Coverage endpoints={catalog.endpoints} />
          <CatalogTable endpoints={catalog.endpoints} />
        </>
      )}
      <RawRequestsDrawer module="M1" />
      <div className="grid gap-6 lg:grid-cols-2">
        <NotesBox questionId="Q4" />
        <NotesBox questionId="Q5" />
      </div>
    </PageShell>
  )
}
