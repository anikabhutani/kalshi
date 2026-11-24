import type { ClockRow, ClockSummary, LabResult, MetadataTimestamp } from '@/lib/api'
import { fmtDuration, fmtNum, fmtPct, fmtUtc } from '@/lib/format'
import { DataTable, type Column } from '@/components/DataTable'
import { StatTile } from '@/components/StatTile'
import { candleLabel, candleSources, tradeSource } from '@/components/timestamps/sources'

interface MetricRow {
  source: string
  endpoint: string
  records: number
  first: string | null
  last: string | null
  covered_s: number
  finest_s: number | null
  median_s: number | null
  max_s: number | null
  slot_s: number
  expected: number
  missing: number | null
  missing_pct: number | null
  no_trade: number
  no_trade_pct: number | null
  longest_s: number
  median_gap_s: number | null
  field: string
  format: string
  note: string
}

function metricRows(result: LabResult): MetricRow[] {
  const rows: MetricRow[] = candleSources(result).map((c) => {
    const m = c.metrics
    const gaps = m.missing_periods
    return {
      source: candleLabel(c.interval_min),
      endpoint: c.endpoint,
      records: m.records,
      first: m.first_ts,
      last: m.last_ts,
      covered_s: m.covered_s,
      finest_s: m.finest_granularity_s,
      median_s: m.median_delta_s,
      max_s: m.max_delta_s,
      slot_s: c.interval_min * 60,
      expected: gaps.expected_slots,
      missing: gaps.empty_slots,
      missing_pct: gaps.empty_pct,
      no_trade: m.periods_without_trade.empty_slots,
      no_trade_pct: m.periods_without_trade.empty_pct,
      longest_s: Math.max(gaps.longest_empty_run_s, m.periods_without_trade.longest_empty_run_s),
      median_gap_s: m.periods_without_trade.median_empty_run_s,
      field: m.timestamp_field,
      format: m.timestamp_format ?? '–',
      note:
        m.alignment_offset_s !== null ? `time slots are shifted ${m.alignment_offset_s}s from round clock times` : '',
    }
  })
  const trades = tradeSource(result)
  if (trades !== null) {
    const m = trades.metrics
    rows.push({
      source: 'trades',
      endpoint: trades.endpoints.join(' + '),
      records: m.records,
      first: m.first_ts,
      last: m.last_ts,
      covered_s: m.covered_s,
      finest_s: m.finest_granularity_s,
      median_s: m.median_delta_s,
      max_s: m.max_delta_s,
      slot_s: m.bucket_s,
      expected: m.empty_buckets.expected_slots,
      missing: null,
      missing_pct: null,
      no_trade: m.empty_buckets.empty_slots,
      no_trade_pct: m.empty_buckets.empty_pct,
      longest_s: m.empty_buckets.longest_empty_run_s,
      median_gap_s: m.empty_buckets.median_empty_run_s,
      field: m.timestamp_field,
      format: m.timestamp_formats.join('; ') || '–',
      note: m.truncated_by_page_cap ? 'hit the page limit: gaps only measured over the trades we fetched' : '',
    })
  }
  return rows
}

const METRIC_COLUMNS: Column<MetricRow>[] = [
  { key: 'source', header: 'Price source', value: (r) => r.source, className: 'font-medium' },
  { key: 'endpoint', header: 'Address', value: (r) => r.endpoint, className: 'font-mono max-w-52 truncate' },
  { key: 'records', header: 'Data points', value: (r) => r.records, render: (r) => fmtNum(r.records), className: 'tabular-nums' },
  { key: 'first', header: 'Earliest', value: (r) => r.first, render: (r) => fmtUtc(r.first), className: 'font-mono' },
  { key: 'last', header: 'Latest', value: (r) => r.last, render: (r) => fmtUtc(r.last), className: 'font-mono' },
  { key: 'covered', header: 'Time span', value: (r) => r.covered_s, render: (r) => fmtDuration(r.covered_s) },
  { key: 'finest', header: 'Smallest Δ', value: (r) => r.finest_s, render: (r) => fmtDuration(r.finest_s) },
  { key: 'median', header: 'Typical Δ', value: (r) => r.median_s, render: (r) => fmtDuration(r.median_s) },
  { key: 'max', header: 'Biggest Δ', value: (r) => r.max_s, render: (r) => fmtDuration(r.max_s) },
  { key: 'slot', header: 'Slot size', value: (r) => r.slot_s, render: (r) => fmtDuration(r.slot_s) },
  { key: 'expected', header: 'Slots in range', value: (r) => r.expected, className: 'tabular-nums' },
  {
    key: 'missing',
    header: 'Empty slots',
    value: (r) => r.missing,
    render: (r) => (r.missing === null ? '–' : `${r.missing} (${fmtPct(r.missing_pct)})`),
  },
  { key: 'missing_pct', header: 'Missing %', value: (r) => r.missing_pct, csvOnly: true },
  {
    key: 'no_trade',
    header: 'Slots with no trades',
    value: (r) => r.no_trade,
    render: (r) => `${r.no_trade} (${fmtPct(r.no_trade_pct)})`,
  },
  { key: 'no_trade_pct', header: 'Without trade %', value: (r) => r.no_trade_pct, csvOnly: true },
  { key: 'longest', header: 'Longest gap', value: (r) => r.longest_s, render: (r) => fmtDuration(r.longest_s) },
  { key: 'median_gap', header: 'Typical gap', value: (r) => r.median_gap_s, render: (r) => fmtDuration(r.median_gap_s) },
  { key: 'field', header: 'Time field used', value: (r) => r.field, className: 'font-mono' },
  { key: 'format', header: 'Time format', value: (r) => r.format },
  { key: 'note', header: 'Note', value: (r) => r.note, className: 'text-muted-foreground' },
]

export function MetricsTable({ result }: { result: LabResult }) {
  return (
    <DataTable
      columns={METRIC_COLUMNS}
      rows={metricRows(result)}
      rowKey={(r) => r.source}
      csvName="m3-source-metrics.csv"
      empty={<p className="text-xs text-muted-foreground">No sources in this run.</p>}
    />
  )
}

const CLOCK_COLUMNS: Column<ClockRow>[] = [
  { key: 'id', header: 'Receipt #', value: (r) => r.request_id, className: 'font-mono' },
  { key: 'path', header: 'Address', value: (r) => r.path, className: 'font-mono max-w-64 truncate' },
  { key: 'status', header: 'Result code', value: (r) => r.status, className: 'font-mono' },
  { key: 'sent', header: 'Sent (our clock)', value: (r) => r.sent_at, render: (r) => fmtUtc(r.sent_at), className: 'font-mono' },
  { key: 'server', header: 'Kalshi’s clock', value: (r) => r.server_date, render: (r) => fmtUtc(r.server_date), className: 'font-mono' },
  { key: 'offset', header: 'Clock difference (s)', value: (r) => r.offset_s, className: 'font-mono tabular-nums' },
  { key: 'latency', header: 'Response time (ms)', value: (r) => r.latency_ms, render: (r) => r.latency_ms.toFixed(0), className: 'tabular-nums' },
]

export function ClockPanel({ rows, summary }: { rows: ClockRow[]; summary: ClockSummary | undefined }) {
  return (
    <div className="grid gap-4">
      {summary !== undefined && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          <StatTile label="Requests" value={summary.requests} />
          <StatTile label="Typical clock difference" value={fmtDuration(summary.offset_median_s)} hint="Kalshi’s clock minus our clock" />
          <StatTile label="Smallest difference" value={fmtDuration(summary.offset_min_s)} />
          <StatTile label="Largest difference" value={fmtDuration(summary.offset_max_s)} />
          <StatTile label="Typical response time" value={`${fmtNum(summary.latency_median_ms)} ms`} />
          <StatTile label="Slowest 5% took over" value={`${fmtNum(summary.latency_p95_ms)} ms`} />
          <StatTile label="Kalshi clock precision" value={`${summary.date_header_resolution_s} s`} hint="Kalshi’s reply clock only shows whole seconds" />
        </div>
      )}
      <DataTable
        columns={CLOCK_COLUMNS}
        rows={rows}
        rowKey={(r) => r.request_id}
        csvName="m3-clock-check.csv"
        maxHeight="max-h-72"
        empty={<p className="text-xs text-muted-foreground">No requests recorded.</p>}
      />
    </div>
  )
}

const META_COLUMNS: Column<MetadataTimestamp>[] = [
  { key: 'field', header: 'Field', value: (r) => r.field, className: 'font-mono' },
  { key: 'value', header: 'Exactly as sent', value: (r) => (r.value === null || r.value === undefined ? null : String(r.value)), className: 'font-mono' },
  { key: 'detected', header: 'Format we found', value: (r) => r.detected_format },
  { key: 'spec', header: 'Format the docs say', value: (r) => r.spec_format, className: 'font-mono' },
  { key: 'utc', header: 'As a normal time (UTC)', value: (r) => r.utc, render: (r) => fmtUtc(r.utc), className: 'font-mono' },
  { key: 'epoch', header: 'Seconds since 1970', value: (r) => r.epoch_s, className: 'font-mono tabular-nums' },
  {
    key: 'description',
    header: 'Docs description',
    value: (r) => r.spec_description,
    render: (r) => (
      <span className="block max-w-md truncate text-muted-foreground" title={r.spec_description ?? ''}>
        {r.spec_description ?? '–'}
      </span>
    ),
  },
]

export function MetadataTable({ rows }: { rows: MetadataTimestamp[] }) {
  return (
    <DataTable
      columns={META_COLUMNS}
      rows={rows}
      rowKey={(r) => r.field}
      csvName="m3-market-timestamps.csv"
      empty={<p className="text-xs text-muted-foreground">No timestamp fields found on the market.</p>}
    />
  )
}
