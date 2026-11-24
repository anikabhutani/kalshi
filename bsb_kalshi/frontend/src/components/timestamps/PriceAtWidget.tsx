import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Crosshair } from 'lucide-react'
import { api, type LabResult, type PriceAtRow } from '@/lib/api'
import { fmtDuration, fmtPrice, fmtUtc, fromUtcInput, toUtcInput } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DataTable, type Column } from '@/components/DataTable'

const COLUMNS: Column<PriceAtRow>[] = [
  { key: 'source', header: 'Price source', value: (r) => r.source, className: 'font-mono' },
  { key: 'field', header: 'Which price', value: (r) => r.field },
  { key: 'price', header: 'Price', value: (r) => r.price, render: (r) => fmtPrice(r.price), className: 'font-mono' },
  { key: 'price_ts', header: 'When that price was set', value: (r) => r.price_ts, render: (r) => fmtUtc(r.price_ts), className: 'font-mono' },
  {
    key: 'staleness',
    header: 'How old it was',
    value: (r) => r.staleness_s,
    render: (r) => <span className="font-mono tabular-nums">{fmtDuration(r.staleness_s)}</span>,
  },
  {
    key: 'flags',
    header: 'Warnings',
    value: (r) => [r.before_first_record && 'before first record', r.after_last_record && 'after last record'].filter(Boolean).join('; '),
    render: (r) => (
      <div className="flex gap-1">
        {r.before_first_record && <Badge className="bg-warning/15 text-warning">before any data</Badge>}
        {r.after_last_record && <Badge className="bg-warning/15 text-warning">after the last data point</Badge>}
      </div>
    ),
  },
  { key: 'records', header: 'Data points', value: (r) => r.records, className: 'tabular-nums' },
  { key: 'note', header: 'Note', value: (r) => r.note, className: 'text-muted-foreground max-w-xs truncate' },
]

/** price_at(market, timestamp, source): latest known price at or before a moment, per source. */
export function PriceAtWidget({
  jobId,
  result,
  onQuery,
}: {
  jobId: string
  result: LabResult
  onQuery: (ts: number | null) => void
}) {
  const { params, market } = result
  const [input, setInput] = useState(toUtcInput(Math.floor((params.start_ts + params.end_ts) / 2)))
  const [at, setAt] = useState<number | null>(null)
  const { data, isFetching } = useQuery({
    queryKey: ['price-at', jobId, at],
    queryFn: () => api.priceAt(jobId, new Date(at! * 1000).toISOString()),
    enabled: at !== null,
  })

  const ask = (ts: number) => {
    setInput(toUtcInput(ts))
    setAt(ts)
    onQuery(ts)
  }
  const quick: { label: string; value: string | number | null | undefined }[] = [
    { label: 'Start of range', value: params.start_ts },
    { label: 'Betting opened', value: market?.open_time },
    { label: 'Game time', value: market?.occurrence_datetime },
    { label: 'Betting closed', value: market?.close_time },
    { label: 'End of range', value: params.end_ts },
  ]

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="price-at-ts">Time (UTC)</Label>
          <Input
            id="price-at-ts"
            type="datetime-local"
            step={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="w-56 font-mono"
          />
        </div>
        <Button
          onClick={() => {
            const ts = fromUtcInput(input)
            if (ts !== null) ask(ts)
          }}
          disabled={isFetching}
        >
          <Crosshair /> Price at this moment
        </Button>
        <div className="flex flex-wrap gap-1.5">
          {quick.map((q) => {
            const ts = typeof q.value === 'number' ? q.value : q.value ? Date.parse(q.value) / 1000 : NaN
            return (
              <Button key={q.label} size="sm" variant="outline" disabled={Number.isNaN(ts)} onClick={() => ask(Math.floor(ts))}>
                {q.label}
              </Button>
            )
          })}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        For each source, this shows the most recent price at or before your chosen time, when that price was actually set, and
        how old it was by then. The chosen time is marked on the chart above. No new requests are sent; it uses the data
        already downloaded.
      </p>
      {data !== undefined && (
        <DataTable
          columns={COLUMNS}
          rows={data.rows}
          rowKey={(r) => `${r.source}-${r.field}`}
          csvName={`m3-price-at-${data.query_ts.replace(/[:+]/g, '')}.csv`}
          empty={null}
        />
      )}
    </div>
  )
}
