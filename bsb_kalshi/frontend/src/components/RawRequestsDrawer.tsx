import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ScrollText } from 'lucide-react'
import { api, type RequestRow } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { cn } from '@/lib/utils'

function statusClass(code: number | null): string {
  if (code === null) return 'bg-muted text-muted-foreground'
  if (code < 300) return 'bg-primary/15 text-primary'
  if (code === 429) return 'bg-warning/15 text-warning'
  return 'bg-destructive/15 text-destructive'
}

const COLUMNS: Column<RequestRow>[] = [
  { key: 'id', header: 'Receipt #', value: (r) => r.id, className: 'font-mono w-12' },
  {
    key: 'time',
    header: 'Time (UTC)',
    value: (r) => r.timestamp_utc,
    render: (r) => <span className="font-mono">{r.timestamp_utc.slice(11, 23)}</span>,
  },
  {
    key: 'endpoint',
    header: 'What we asked Kalshi for',
    value: (r) => r.url,
    render: (r) => (
      <span className="block max-w-md truncate font-mono" title={r.url}>
        GET {r.url.replace(/^https?:\/\/[^/]+/, '')}
      </span>
    ),
  },
  { key: 'auth', header: 'Used account key?', value: (r) => (r.auth_used ? 'yes' : 'no') },
  {
    key: 'status',
    header: 'Result code (200 = OK)',
    value: (r) => r.status_code,
    render: (r) => <Badge className={cn('font-mono', statusClass(r.status_code))}>{r.status_code ?? 'ERR'}</Badge>,
  },
  {
    key: 'latency',
    header: 'Response time',
    value: (r) => r.latency_ms,
    render: (r) => <span className="font-mono tabular-nums">{r.latency_ms?.toFixed(0) ?? '–'} ms</span>,
  },
  { key: 'bytes', header: 'Size (bytes)', value: (r) => r.response_bytes, className: 'font-mono tabular-nums' },
  { key: 'error', header: 'Error', value: (r) => r.error, className: 'text-destructive max-w-xs truncate' },
]

function RequestsTable({ jobId, module }: { jobId?: string; module?: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['requests', jobId ?? null, module ?? null],
    queryFn: () => api.requests({ jobId, module, limit: 500 }),
  })
  if (isLoading || data === undefined) return <Skeleton className="h-32 w-full" />
  return (
    <DataTable
      columns={COLUMNS}
      rows={data}
      rowKey={(r) => r.id}
      csvName={`requests-${jobId ?? module ?? 'all'}.csv`}
      empty={
        <EmptyState icon={ScrollText} title="No requests yet">
          Run a test on this page and every request it sends to Kalshi will be listed here.
        </EmptyState>
      }
    />
  )
}

export function RawRequestsDrawer({ jobId, module }: { jobId?: string; module?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-xl border bg-card">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-5 py-3.5 text-left text-sm font-semibold hover:bg-accent/40">
        <ScrollText className="size-4 text-muted-foreground" />
        Receipts: every request sent to Kalshi
        <span className="text-xs font-normal text-muted-foreground">
          {jobId !== undefined ? 'for this test' : module !== undefined ? 'from this page' : ''} (proof for the report)
        </span>
        <ChevronDown className={cn('ml-auto size-4 transition-transform', open && 'rotate-180')} />
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t p-5">{open && <RequestsTable jobId={jobId} module={module} />}</CollapsibleContent>
    </Collapsible>
  )
}
