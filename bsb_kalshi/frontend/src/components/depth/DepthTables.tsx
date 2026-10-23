import { Badge } from '@/components/ui/badge'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import type { DepthResult, DepthTargetResult, MatrixCell, MatrixSample } from '@/lib/api'
import { fmtDuration, fmtUtc } from '@/lib/format'
import { History, Table2 } from 'lucide-react'

function requestsUsed(t: DepthTargetResult): number {
  return t.probes?.length ?? t.pages?.length ?? 0
}

const DEPTH_COLUMNS: Column<DepthTargetResult>[] = [
  { key: 'label', header: 'Kind of data', value: (t) => t.label, className: 'min-w-44' },
  { key: 'path', header: 'Address', value: (t) => `GET ${t.path}`, className: 'font-mono' },
  { key: 'mode', header: 'How we searched', value: (t) => (t.mode === 'bisect' ? `date-range search (${t.bound_param})` : 'flipped through pages') },
  { key: 'ts', header: 'Date field', value: (t) => t.ts_field, className: 'font-mono' },
  {
    key: 'filters',
    header: 'Filters used',
    value: (t) => Object.entries(t.filters_applied).map(([k, v]) => `${k}=${v}`).join(' ') || '–',
    className: 'font-mono',
  },
  { key: 'oldest', header: 'Oldest found', value: (t) => t.oldest_ts ?? null, render: (t) => fmtUtc(t.oldest_ts ?? null) },
  { key: 'newest', header: 'Newest found', value: (t) => t.newest_ts ?? null, render: (t) => fmtUtc(t.newest_ts ?? null) },
  {
    key: 'bracket',
    header: 'True oldest is between',
    value: (t) => t.bracket_lo ?? null,
    render: (t) =>
      t.bracket_lo != null && t.bracket_hi != null
        ? `${fmtUtc(t.bracket_lo, false)} → ${fmtUtc(t.bracket_hi, false)} (${fmtDuration(t.bracket_hi - t.bracket_lo)})`
        : t.beyond_lower_bound
          ? `older than where we stopped looking (${fmtUtc(t.bracket_hi ?? null, false)})`
          : '–',
  },
  { key: 'records', header: 'Records seen', value: (t) => t.records_seen ?? null, csvOnly: true },
  { key: 'end', header: 'End reached', value: (t) => (t.mode === 'walk' ? Boolean(t.end_reached) : null), csvOnly: true },
  { key: 'requests', header: 'Requests used', value: requestsUsed, className: 'text-right tabular-nums' },
  {
    key: 'stop',
    header: 'Note',
    value: (t) => (t.no_records ? 'no records returned' : (t.stop_reason ?? '')),
    render: (t) =>
      t.no_records ? (
        <Badge variant="secondary">Kalshi returned nothing</Badge>
      ) : t.stop_reason ? (
        <Badge className="bg-warning/15 text-warning">{t.stop_reason}</Badge>
      ) : (
        '–'
      ),
  },
]

export function DepthTable({ result }: { result: DepthResult }) {
  return (
    <DataTable
      columns={DEPTH_COLUMNS}
      rows={result.targets}
      rowKey={(t) => t.id}
      csvName="m4-depth.csv"
      empty={<EmptyState icon={History} title="Nothing was tested in this run" />}
    />
  )
}

interface MatrixRow {
  sample: MatrixSample
  cell: MatrixCell
}

function statusBadge(cell: MatrixCell) {
  if (cell.status === null) return <span className="text-muted-foreground">{cell.note ?? 'not checked'}</span>
  const ok = cell.status >= 200 && cell.status < 300
  const tone = !ok ? 'bg-destructive/15 text-destructive' : (cell.records ?? 0) > 0 ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'
  const label = !ok ? `not found (${cell.status})` : (cell.records ?? 0) > 0 ? `found (${cell.status})` : `empty (${cell.status})`
  return <Badge className={`font-mono ${tone}`}>{label}</Badge>
}

const MATRIX_COLUMNS: Column<MatrixRow>[] = [
  { key: 'sample', header: 'Example', value: (r) => r.sample.label, className: 'min-w-48' },
  { key: 'ticker', header: 'Bet code', value: (r) => r.sample.ticker, className: 'font-mono' },
  { key: 'status_m', header: 'Bet status', value: (r) => r.sample.status ?? null },
  { key: 'settled', header: 'Paid out at', value: (r) => r.sample.settlement_ts ?? null, render: (r) => fmtUtc(r.sample.settlement_ts ?? null) },
  { key: 'side', header: 'Side of cutoff', value: (r) => r.sample.cutoff_side ?? null },
  { key: 'check', header: 'Looked in', value: (r) => r.cell.check },
  { key: 'endpoint', header: 'Address', value: (r) => r.cell.endpoint, className: 'font-mono' },
  { key: 'http', header: 'Result', value: (r) => r.cell.status, render: (r) => statusBadge(r.cell) },
  { key: 'records', header: 'Data points', value: (r) => r.cell.records, className: 'text-right tabular-nums' },
  { key: 'request', header: 'Receipt #', value: (r) => r.cell.request_id, className: 'font-mono text-muted-foreground' },
]

export function MatrixTable({ result }: { result: DepthResult }) {
  const rows = (result.matrix?.samples ?? []).flatMap((sample) => sample.cells.map((cell) => ({ sample, cell })))
  return (
    <DataTable
      columns={MATRIX_COLUMNS}
      rows={rows}
      rowKey={(r) => `${r.sample.ticker}-${r.cell.check}`}
      csvName="m4-archive-matrix.csv"
      empty={
        <EmptyState icon={Table2} title="Live vs archive check was not run">
          {result.matrix?.stop_reason ?? 'Tick “Also check live vs archive for example bets” and run again.'}
        </EmptyState>
      }
    />
  )
}
