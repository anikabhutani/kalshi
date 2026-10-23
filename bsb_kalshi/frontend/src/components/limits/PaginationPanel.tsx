import { useMemo, useState } from 'react'
import { Layers, Play } from 'lucide-react'
import { api, type BoundaryRow, type PageRow, type PaginationParams, type PaginationResult, type RateDoc } from '@/lib/api'
import { paginationFigure } from '@/lib/figures'
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
import { StatTile } from '@/components/StatTile'

const statusBadge = (status: number | null) =>
  status === null ? (
    '–'
  ) : (
    <Badge className={`font-mono ${status >= 200 && status < 300 ? 'bg-primary/15 text-primary' : 'bg-destructive/15 text-destructive'}`}>
      {status >= 200 && status < 300 ? 'OK' : 'rejected'} ({status})
    </Badge>
  )

const BOUNDARY_COLUMNS: Column<BoundaryRow>[] = [
  { key: 'case', header: 'What we tried', value: (b) => b.case, className: 'min-w-48' },
  { key: 'size', header: 'Page size asked for', value: (b) => b.size_sent ?? 'not specified', className: 'font-mono' },
  { key: 'status', header: 'Result', value: (b) => b.status, render: (b) => statusBadge(b.status) },
  { key: 'items', header: 'Items returned', value: (b) => b.items, className: 'text-right tabular-nums' },
  { key: 'cursor', header: '“Next page” link given?', value: (b) => (b.cursor_returned === null ? null : b.cursor_returned ? 'yes' : 'no') },
  { key: 'error', header: 'Kalshi’s error message', value: (b) => b.error_sample, className: 'max-w-sm truncate font-mono' },
  { key: 'req', header: 'Receipt #', value: (b) => b.request_id, className: 'font-mono text-muted-foreground' },
]

const PAGE_COLUMNS: Column<PageRow>[] = [
  { key: 'page', header: 'Page', value: (p) => p.page, className: 'text-right tabular-nums' },
  { key: 'status', header: 'Result', value: (p) => p.status, render: (p) => statusBadge(p.status) },
  { key: 'items', header: 'Items', value: (p) => p.items, className: 'text-right tabular-nums' },
  { key: 'dups', header: 'Repeats from earlier pages', value: (p) => p.duplicates_of_earlier_pages, className: 'text-right tabular-nums' },
  { key: 'clen', header: '“Next page” link length', value: (p) => p.cursor_length, className: 'text-right tabular-nums' },
  { key: 'cpre', header: 'Link starts with', value: (p) => p.cursor_prefix, className: 'font-mono' },
  { key: 'crep', header: 'Same link as before?', value: (p) => (p.cursor_repeated ? 'yes' : 'no') },
  { key: 'end', header: 'How the end was signalled', value: (p) => p.end_signal },
  { key: 'req', header: 'Receipt #', value: (p) => p.request_id, className: 'font-mono text-muted-foreground' },
]

function parseFilters(text: string): Record<string, string> {
  return Object.fromEntries([...new URLSearchParams(text.trim()).entries()].filter(([k, v]) => k !== '' && v !== ''))
}

function PaginationResults({ result }: { result: PaginationResult }) {
  const figure = useMemo(() => paginationFigure(result), [result])
  const s = result.summary
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Normal page size (docs)" value={result.spec.size_default ?? '–'} />
        <StatTile label="Smallest / largest allowed" value={`${result.spec.size_minimum ?? '–'} / ${result.spec.size_maximum ?? '–'}`} />
        <StatTile label="Page size we used" value={result.walk_size} />
        <StatTile label="Different items seen" value={s?.unique_items ?? '–'} hint={s?.identity_key ? `told apart by ${s.identity_key}` : undefined} />
        <StatTile label="Repeated items" value={s?.duplicate_items ?? '–'} tone={(s?.duplicate_items ?? 0) > 0 ? 'warning' : 'default'} />
        <StatTile label="Reached the last page?" value={s ? (s.last_page_reached ? 'yes' : 'no') : '–'} hint={s?.last_page_signal ?? undefined} />
      </div>
      {result.spec.cursor_description && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">What Kalshi’s docs say about the “next page” link (cursor): </span>
          {result.spec.cursor_description}
        </p>
      )}
      {result.boundary.length > 0 && (
        <div className="grid gap-1">
          <h3 className="text-xs font-semibold">Testing the page-size limits</h3>
          <DataTable columns={BOUNDARY_COLUMNS} rows={result.boundary} rowKey={(b) => b.case} csvName="m5-pagination-boundaries.csv" empty="–" />
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
        <div className="grid content-start gap-1">
          <h3 className="text-xs font-semibold">Flipping through pages</h3>
          <DataTable columns={PAGE_COLUMNS} rows={result.pages} rowKey={(p) => p.page} csvName="m5-pagination-pages.csv" empty="No pages fetched." />
        </div>
        <div className="grid content-start gap-1">
          <h3 className="text-xs font-semibold">Items per page</h3>
          {figure && <Chart data={figure.data} layout={figure.layout} height={figure.height} filename="m5-pagination" />}
        </div>
      </div>
      {s && (
        <p className="text-xs text-muted-foreground">
          Last page: {s.last_page_items ?? '–'} items. How Kalshi signalled the end: “
          {s.last_page_signal ?? 'it didn’t; we hit our page limit first'}”
          {s.last_page_reached && `, ${s.last_page_smaller_than_size ? 'smaller than' : 'equal to'} a full page`}.
        </p>
      )}
    </div>
  )
}

export function PaginationPanel({ doc, job }: { doc: RateDoc; job: ModuleJob<PaginationResult> }) {
  const initial = doc.pagination_choices.find((c) => c.path === '/markets') ?? doc.pagination_choices[0]
  const [path, setPath] = useState(initial?.path ?? '')
  const [filters, setFilters] = useState('')
  const [walkSize, setWalkSize] = useState<number | null>(null)
  const [pageCap, setPageCap] = useState(5)
  const [boundary, setBoundary] = useState(true)
  const choice = doc.pagination_choices.find((c) => c.path === path)
  const guarded = useGuardedRun<PaginationParams>({
    plan: async (p) => (await api.paginationPlan(p)).estimate,
    run: api.runPagination,
    onStarted: job.start,
  })
  const params: PaginationParams = { path, filters: parseFilters(filters), walk_size: walkSize, page_cap: pageCap, boundary_tests: boundary }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="m5-pg-path">List to test</Label>
          <NativeSelect id="m5-pg-path" value={path} onChange={(e) => setPath(e.target.value)} className="w-64 font-mono">
            {doc.pagination_choices.map((c) => (
              <option key={c.path} value={c.path}>
                {c.path}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="grid min-w-64 flex-1 gap-1.5">
          <Label htmlFor="m5-pg-filters">Filters (optional)</Label>
          <Input id="m5-pg-filters" value={filters} onChange={(e) => setFilters(e.target.value)} placeholder="e.g. status=open&series_ticker=…" className="font-mono" />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="m5-pg-size">Items per page</Label>
          <Input
            id="m5-pg-size"
            type="number"
            min={1}
            value={walkSize ?? ''}
            placeholder={String(choice?.size_default ?? 100)}
            onChange={(e) => setWalkSize(e.target.value === '' ? null : Math.max(1, Number(e.target.value) || 1))}
            className="w-32 font-mono"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="m5-pg-cap">Max pages</Label>
          <Input
            id="m5-pg-cap"
            type="number"
            min={1}
            max={30}
            value={pageCap}
            onChange={(e) => setPageCap(Math.min(30, Math.max(1, Number(e.target.value) || 1)))}
            className="w-24 font-mono"
          />
        </div>
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" className="accent-primary" checked={boundary} onChange={(e) => setBoundary(e.target.checked)} />
          Also test the page-size limits
        </label>
        <Button size="lg" className="ml-auto" disabled={guarded.busy || job.running || path === ''} onClick={() => guarded.request(params)}>
          <Play /> Run page test
        </Button>
      </div>
      {choice && (
        <p className="text-xs text-muted-foreground">
          Kalshi’s docs: page size (<span className="font-mono">{choice.size_param}</span>) is normally {choice.size_default ?? '–'}, smallest{' '}
          {choice.size_minimum ?? '–'}, largest {choice.size_maximum ?? '–'}. Filters you can use:{' '}
          <span className="font-mono">{choice.filter_params.join(', ') || 'none'}</span>
        </p>
      )}
      {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
      {job.job?.result ? (
        <PaginationResults key={job.job.id} result={job.job.result} />
      ) : (
        !job.running && (
          <EmptyState icon={Layers} title="No page test yet">
            Pick a list and press “Run page test”.
          </EmptyState>
        )
      )}
      <RunConfirmDialog
        open={guarded.dialogOpen}
        onOpenChange={(open) => !open && guarded.closeDialog()}
        title="Run page test"
        estimate={guarded.estimate}
        breakdown={[
          { label: 'Page-size limit tests', value: guarded.estimate?.boundary ?? 0 },
          { label: 'Pages to flip through (at most)', value: guarded.estimate?.walk_pages ?? 0 },
        ]}
        notes={['Stops early once Kalshi says there are no more pages.']}
        onConfirm={guarded.confirm}
        confirming={guarded.confirming}
      />
    </div>
  )
}
