import { useMemo } from 'react'
import { Radio, TriangleAlert } from 'lucide-react'
import type { Distribution, PollInterval, RecorderResult, SequenceRow, WsConnectionRow } from '@/lib/api'
import type { Figure } from '@/lib/figures'
import { fmtNum, fmtUtc } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Chart } from '@/components/charts/Chart'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { Section } from '@/components/PageShell'
import { StatTile } from '@/components/StatTile'
import { cumulativeUpdatesFigure, eventTimelineFigure, latencyHistogramFigure, priceComparisonFigure } from '@/components/restws/recorderFigures'

const ms = (value: number | null | undefined) => (value === null || value === undefined ? '–' : `${fmtNum(value)} ms`)
const msUtc = (value: number) => fmtUtc(new Date(value).toISOString())

interface MetricRow {
  metric: string
  value: string | number | null
  definition: string
}

interface LatencyRow {
  type: string
  measure: string
  dist: Distribution
}

const METRIC_COLUMNS: Column<MetricRow>[] = [
  { key: 'metric', header: 'What we measured', value: (r) => r.metric, className: 'font-medium' },
  { key: 'value', header: 'Result', value: (r) => r.value, className: 'text-right font-mono tabular-nums' },
  { key: 'def', header: 'What it means', value: (r) => r.definition, className: 'whitespace-normal text-muted-foreground' },
]

const LATENCY_COLUMNS: Column<LatencyRow>[] = [
  { key: 'type', header: 'Kind of message', value: (r) => r.type, className: 'font-mono' },
  { key: 'measure', header: 'Measured against', value: (r) => r.measure, className: 'font-mono' },
  { key: 'n', header: 'Count', value: (r) => r.dist.count, className: 'text-right tabular-nums' },
  { key: 'min', header: 'Fastest (ms)', value: (r) => r.dist.min, className: 'text-right tabular-nums' },
  { key: 'median', header: 'Typical (ms)', value: (r) => r.dist.median, className: 'text-right tabular-nums' },
  { key: 'p95', header: 'Slowest 5% (ms)', value: (r) => r.dist.p95, className: 'text-right tabular-nums' },
  { key: 'max', header: 'Slowest (ms)', value: (r) => r.dist.max, className: 'text-right tabular-nums' },
]

const INTERVAL_COLUMNS: Column<PollInterval>[] = [
  { key: 'start', header: 'From check', value: (r) => msUtc(r.start_ms), className: 'font-mono' },
  { key: 'end', header: 'To next check', value: (r) => msUtc(r.end_ms), className: 'font-mono' },
  { key: 'ws', header: 'Changes on live stream', value: (r) => r.ws_changes, className: 'text-right tabular-nums' },
  { key: 'rest', header: 'Did checking see a change?', value: (r) => (r.rest_changed ? 'yes' : 'no') },
  { key: 'missed', header: 'Missed by checking', value: (r) => r.missed, className: 'text-right tabular-nums' },
]

const CONNECTION_COLUMNS: Column<WsConnectionRow>[] = [
  { key: 'attempt', header: 'Attempt', value: (r) => r.attempt, className: 'text-right tabular-nums' },
  { key: 'at', header: 'Time', value: (r) => msUtc(r.at_ms), className: 'font-mono' },
  { key: 'status', header: 'Result code', value: (r) => r.status, className: 'font-mono' },
  { key: 'latency', header: 'Time to connect (ms)', value: (r) => r.latency_ms, className: 'text-right tabular-nums' },
  { key: 'error', header: 'Problem', value: (r) => r.error, className: 'whitespace-normal' },
  { key: 'req', header: 'Receipt #', value: (r) => r.request_id, className: 'font-mono' },
]

const SEQUENCE_COLUMNS: Column<SequenceRow>[] = [
  { key: 'sid', header: 'Feed ID', value: (r) => r.sid, className: 'font-mono' },
  { key: 'types', header: 'Kinds of message', value: (r) => r.types.join(', '), className: 'font-mono' },
  { key: 'n', header: 'Messages', value: (r) => r.messages, className: 'text-right tabular-nums' },
  { key: 'first', header: 'First number', value: (r) => r.first_seq, className: 'text-right tabular-nums' },
  { key: 'last', header: 'Last number', value: (r) => r.last_seq, className: 'text-right tabular-nums' },
  { key: 'missing', header: 'Numbers skipped', value: (r) => r.missing, className: 'text-right tabular-nums' },
  { key: 'ooo', header: 'Out of order', value: (r) => r.out_of_order, className: 'text-right tabular-nums' },
]

function metricRows(r: RecorderResult): MetricRow[] {
  const c = r.comparison
  const t = r.trades
  return [
    { metric: 'Live stream: messages received', value: r.ws.messages, definition: 'Every message Kalshi pushed to us, of any kind.' },
    { metric: 'Live stream: price changes', value: r.ws.price_changes, definition: 'Times the bid, ask, or last price changed according to the live stream.' },
    { metric: 'Checking: successful price checks', value: `${r.rest.ok_polls} of ${r.rest.polls}`, definition: 'Price checks that came back with a price we could compare.' },
    { metric: 'Checking: price changes noticed', value: c.rest_changes, definition: 'Checks where the price was different from the previous check.' },
    { metric: 'Live stream changes between checks', value: c.ws_changes_between_polls, definition: 'Price changes the live stream reported between the first and last check.' },
    { metric: 'Changes missed by checking', value: c.rest_missed_changes, definition: 'Between two checks, checking can notice at most one change. Any extra changes the live stream saw in that gap (e.g. the price moved and moved back) count as missed.' },
    { metric: 'Gaps where only the live stream saw a change', value: c.intervals_ws_changed_rest_unchanged, definition: 'Includes changes that reversed before the next check.' },
    { metric: 'Gaps where only checking saw a change', value: c.intervals_rest_changed_ws_unchanged, definition: 'Checking saw a new price but the live stream reported no change in that gap.' },
    { metric: 'Gaps with more than one change', value: c.intervals_multiple_ws_changes, definition: `Out of ${c.intervals} gaps between checks in total.` },
    { metric: 'Trades seen: live stream / checking', value: `${t.ws_trades} / ${t.rest_trades}`, definition: 'Trades that happened while both methods were running.' },
    { metric: 'Trades seen by both', value: t.matched, definition: `Only on live stream: ${t.ws_only}; only from checking: ${t.rest_only}.` },
    { metric: 'How much later checking saw a trade (typical)', value: ms(t.rest_delay_after_ws_ms.median), definition: 'For trades seen by both: how long after the live stream checking first saw it.' },
    { metric: 'Time for one price check (typical)', value: ms(r.rest.latency_ms.median), definition: `Slowest 5% over ${ms(r.rest.latency_ms.p95)}; slowest ${ms(r.rest.latency_ms.max)}.` },
    { metric: 'Kalshi’s clock vs ours (typical)', value: r.rest.clock_offset_median_s === null ? '–' : `${r.rest.clock_offset_median_s.toFixed(2)} s`, definition: 'Kalshi’s clock minus our computer’s clock (only accurate to 1 second). Live stream delay figures include this difference.' },
    { metric: 'Live stream connections / reconnects', value: `${r.connections.length} / ${r.reconnects}`, definition: `Times the connection dropped: ${r.disconnects.length}.` },
    { metric: 'Live stream error messages', value: r.ws.errors.length, definition: 'Messages where Kalshi reported an error.' },
    { metric: 'Trade checks that hit the page limit', value: r.rest.trade_pages_full, definition: 'Trade checks that returned a completely full page, so some trades may not have fit.' },
  ]
}

function ChartBlock({ title, figure, filename, empty }: { title: string; figure: Figure | null; filename: string; empty: string }) {
  return (
    <div className="grid gap-1">
      <h3 className="text-xs font-semibold">{title}</h3>
      {figure ? <Chart data={figure.data} layout={figure.layout} height={figure.height} filename={filename} /> : <p className="text-xs text-muted-foreground">{empty}</p>}
    </div>
  )
}

export function RecorderResults({ jobId, result }: { jobId: string; result: RecorderResult }) {
  const timeline = useMemo(() => eventTimelineFigure(result), [result])
  const prices = useMemo(() => priceComparisonFigure(result), [result])
  const latency = useMemo(() => latencyHistogramFigure(result), [result])
  const cumulative = useMemo(() => cumulativeUpdatesFigure(result), [result])
  const metrics = useMemo(() => metricRows(result), [result])
  const latencyRows = useMemo(
    () =>
      Object.entries(result.ws.latency).flatMap(([type, l]) => [
        { type, measure: 'when it happened (ts_ms)', dist: l.recv_minus_ts_ms },
        { type, measure: 'when Kalshi sent it (sending_ts_ms)', dist: l.recv_minus_sending_ts_ms },
      ]),
    [result],
  )
  const tickerLatency = result.ws.latency.ticker?.recv_minus_ts_ms.median ?? null

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        Started {fmtUtc(result.started_at)}
        <Badge variant="outline" className="font-mono">
          run {jobId.slice(0, 8)}
        </Badge>
        <span className="font-mono text-foreground">{result.params.market_ticker}</span>
        <span>
          recorded {result.recorded_s}s of {result.planned_duration_s}s · checked every {result.params.poll_interval_s}s · live feeds{' '}
          {result.params.channels.join(', ')}
        </span>
        {result.market_status !== null && <Badge variant="secondary">bet status: {result.market_status}</Badge>}
        {result.partial && <Badge className="bg-warning/15 text-warning">incomplete: test was stopped early</Badge>}
      </div>
      {(result.stopped_reason !== null || result.ws.events_truncated) && (
        <div className="grid gap-1 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-warning">
          {result.stopped_reason !== null && (
            <div className="flex items-center gap-2">
              <TriangleAlert className="size-3.5 shrink-0" /> Stopped: {result.stopped_reason}
            </div>
          )}
          {result.ws.events_truncated && (
            <div className="flex items-center gap-2">
              <TriangleAlert className="size-3.5" /> Charts show the first {result.ws.events_stored} messages; every message is saved in{' '}
              {result.ws.raw_file}.
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <StatTile label="Live stream messages" value={fmtNum(result.ws.messages)} tone="primary" />
        <StatTile label="Price changes (live stream)" value={fmtNum(result.ws.price_changes)} />
        <StatTile label="Price checks made" value={fmtNum(result.rest.polls)} />
        <StatTile label="Changes noticed by checking" value={fmtNum(result.comparison.rest_changes)} />
        <StatTile label="Changes checking missed" value={fmtNum(result.comparison.rest_missed_changes)} tone={result.comparison.rest_missed_changes > 0 ? 'warning' : 'default'} />
        <StatTile label="Live stream delay (typical)" value={ms(tickerLatency)} hint="How long after a price change it reached us; includes any clock difference" />
        <StatTile label="Times reconnected" value={result.reconnects} tone={result.reconnects > 0 ? 'warning' : 'default'} />
        <StatTile label="Live stream errors" value={result.ws.errors.length} tone={result.ws.errors.length > 0 ? 'destructive' : 'default'} />
      </div>

      <Section title="Timeline: live stream vs checking" description="Each tick is one message from the live stream or one price check, at the moment it reached us. Hover for details.">
        {timeline ? (
          <Chart data={timeline.data} layout={timeline.layout} height={timeline.height} filename="m6-event-timeline" />
        ) : (
          <EmptyState icon={Radio} title="Nothing was recorded" />
        )}
      </Section>

      <Section title="Charts" description="The price according to each method, how fast updates arrived, and running totals.">
        <div className="grid gap-6">
          <ChartBlock title="Price over time: live stream (lines) vs checking (dots)" figure={prices} filename="m6-prices" empty="No prices were recorded." />
          <div className="grid gap-6 xl:grid-cols-2">
            <ChartBlock title="How fast live updates arrived" figure={latency} filename="m6-latency-histogram" empty="No messages carried a time." />
            <ChartBlock title="Running total of updates" figure={cumulative} filename="m6-cumulative-updates" empty="Nothing recorded." />
          </div>
        </div>
      </Section>

      <Section title="The numbers" description="Every value is counted directly from what was recorded. The explanations are fixed text, not generated.">
        <div className="grid gap-6">
          <DataTable columns={METRIC_COLUMNS} rows={metrics} rowKey={(r) => r.metric} csvName="m6-metrics.csv" empty="No metrics." />
          <div className="grid gap-1">
            <h3 className="text-xs font-semibold">How long live messages took to reach us, by kind</h3>
            <DataTable columns={LATENCY_COLUMNS} rows={latencyRows} rowKey={(r) => `${r.type}-${r.measure}`} csvName="m6-latency.csv" empty={<p className="text-xs text-muted-foreground">No messages carried a time.</p>} />
          </div>
          <div className="grid gap-1">
            <h3 className="text-xs font-semibold">Which price fields were compared</h3>
            <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr_1fr]">
              {result.field_pairing.map((f) => (
                <div key={f.state} className="contents">
                  <dt className="text-muted-foreground">{f.state}</dt>
                  <dd className="font-mono">checking: {f.rest}</dd>
                  <dd className="font-mono">live stream: {f.websocket}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </Section>

      <Section title="Gap by gap" description="For each gap between two price checks: how many changes the live stream saw, and whether checking noticed.">
        <DataTable columns={INTERVAL_COLUMNS} rows={result.comparison.per_interval} rowKey={(r) => r.start_ms} csvName="m6-poll-intervals.csv" empty={<p className="text-xs text-muted-foreground">Fewer than two successful checks.</p>} />
      </Section>

      <Section title="Live stream connection details" description={`Stream address ${result.ws_url}. Every message is saved in ${result.ws.raw_file}.`}>
        <div className="grid gap-6">
          <DataTable columns={CONNECTION_COLUMNS} rows={result.connections} rowKey={(r) => r.attempt} csvName="m6-connections.csv" empty={<p className="text-xs text-muted-foreground">No connection attempts.</p>} />
          <div className="grid gap-1">
            <h3 className="text-xs font-semibold">Kalshi’s confirmations that we were subscribed</h3>
            {result.acks.length === 0 ? (
              <p className="text-xs text-muted-foreground">No confirmations received.</p>
            ) : (
              <ul className="grid gap-1 font-mono text-xs">
                {result.acks.map((a, i) => (
                  <li key={i} className={a.type === 'error' ? 'text-destructive' : undefined}>
                    attempt {a.attempt}: {a.type} {a.msg?.channel ?? ''} {a.msg?.sid !== undefined ? `sid ${a.msg.sid}` : ''}{' '}
                    {a.msg?.code !== undefined ? `code ${a.msg.code}: ${a.msg.msg ?? ''}` : ''}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="grid gap-1">
            <h3 className="text-xs font-semibold">Did any live messages go missing? (each message is numbered)</h3>
            <DataTable columns={SEQUENCE_COLUMNS} rows={result.ws.sequence} rowKey={(r) => String(r.sid)} csvName="m6-sequence.csv" empty={<p className="text-xs text-muted-foreground">No messages carried a number.</p>} />
          </div>
          {result.disconnects.length > 0 && (
            <div className="grid gap-1">
              <h3 className="text-xs font-semibold">Times the connection dropped</h3>
              <ul className="grid gap-1 font-mono text-xs">
                {result.disconnects.map((d) => (
                  <li key={`${d.attempt}-${d.at_ms}`}>
                    attempt {d.attempt} at {msUtc(d.at_ms)}: code {d.code ?? '–'} {d.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            Messages by kind: {Object.entries(result.ws.message_counts).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none'}
          </p>
        </div>
      </Section>
    </>
  )
}
