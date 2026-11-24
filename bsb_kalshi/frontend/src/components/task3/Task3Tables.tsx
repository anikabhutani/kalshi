import { Table2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { DataTable, type CellValue, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import type { T3CostRow, T3CutoffSample, T3Game, T3QualityByType, T3QualityMarket } from '@/lib/api'
import { fmtNum, fmtUtc } from '@/lib/format'
import { CHECKPOINT_LABEL } from '@/components/task3/figures'

const money = (v: number | null | undefined) => (v === null || v === undefined ? '–' : `$${v.toFixed(2)}`)
const num = 'text-right tabular-nums'

function httpBadge(code: number | null | undefined) {
  if (code === null || code === undefined) return '–'
  const ok = code >= 200 && code < 300
  return <Badge className={ok ? 'bg-primary/15 text-primary' : 'bg-destructive/15 text-destructive'}>{code}</Badge>
}

const GAME_COLUMNS: Column<T3Game>[] = [
  { key: 'week', header: 'Week', value: (g) => g.week, className: num },
  { key: 'title', header: 'Game', value: (g) => g.title, className: 'min-w-48' },
  { key: 'kickoff', header: 'Kickoff', value: (g) => g.kickoff_utc, render: (g) => fmtUtc(g.kickoff_utc, false) },
  { key: 'kickoff_source', header: 'Kickoff from', value: (g) => g.kickoff_source, csvOnly: true },
  { key: 'game', header: 'Winner bets', value: (g) => g.game_markets, className: num },
  { key: 'spread', header: 'Spread bets', value: (g) => g.spread_markets, className: num },
  { key: 'total', header: 'Total bets', value: (g) => g.total_markets, className: num },
  { key: 'settled', header: 'Settled', value: (g) => g.settled, render: (g) => `${g.settled}/${g.markets}`, className: num },
  { key: 'complete', header: 'Fully downloaded', value: (g) => g.complete, render: (g) => `${g.complete}/${g.markets}`, className: num },
  { key: 'candles', header: 'Minutes stored', value: (g) => g.candles, render: (g) => fmtNum(g.candles), className: num },
  { key: 'errors', header: 'Fetch errors', value: (g) => g.errors, className: num },
  { key: 'key', header: 'Game code', value: (g) => g.game_key, className: 'font-mono' },
]

export function GamesTable({ games }: { games: T3Game[] }) {
  return (
    <DataTable
      columns={GAME_COLUMNS}
      rows={games}
      rowKey={(g) => g.game_key}
      csvName="task3-games.csv"
      empty={<EmptyState icon={Table2} title="No games listed yet" />}
    />
  )
}

const CUTOFF_COLUMNS: Column<T3CutoffSample>[] = [
  { key: 'label', header: 'Sample', value: (s) => s.label, className: 'min-w-48' },
  { key: 'ticker', header: 'Bet code', value: (s) => s.ticker, className: 'font-mono' },
  { key: 'settled', header: 'Settled', value: (s) => s.settlement_ts, render: (s) => fmtUtc(s.settlement_ts, false) },
  { key: 'side', header: 'Side of cutoff', value: (s) => s.side },
  { key: 'live', header: 'Live market', value: (s) => s.live_market_status, render: (s) => httpBadge(s.live_market_status) },
  { key: 'hist', header: 'Archive market', value: (s) => s.historical_market_status, render: (s) => httpBadge(s.historical_market_status) },
  {
    key: 'batch',
    header: 'Batch candles (last hour)',
    value: (s) => s.batch_candles ?? null,
    render: (s) => (
      <span className="inline-flex items-center gap-1.5">
        {httpBadge(s.batch_status)} {s.batch_candles ?? '–'}
      </span>
    ),
  },
  {
    key: 'histc',
    header: 'Archive candles (last hour)',
    value: (s) => s.historical_candles ?? null,
    render: (s) => (
      <span className="inline-flex items-center gap-1.5">
        {httpBadge(s.historical_candles_status)} {s.historical_candles ?? '–'}
      </span>
    ),
  },
  {
    key: 'receipts',
    header: 'Receipts',
    value: (s) =>
      [s.live_market_request_id, s.historical_market_request_id, s.batch_request_id, s.historical_candles_request_id]
        .filter((x) => x !== undefined)
        .join(' '),
    className: 'font-mono',
  },
]

export function CutoffSamplesTable({ samples }: { samples: T3CutoffSample[] }) {
  return (
    <DataTable
      columns={CUTOFF_COLUMNS}
      rows={samples}
      rowKey={(s) => s.ticker}
      csvName="task3-cutoff-check.csv"
      empty={<EmptyState icon={Table2} title="No samples checked" />}
    />
  )
}

export function CostTable({
  rows,
  keyHeader,
  keyValue,
  csvName,
}: {
  rows: T3CostRow[]
  keyHeader: string
  keyValue: (r: T3CostRow) => CellValue
  csvName: string
}) {
  const columns: Column<T3CostRow>[] = [
    { key: 'checkpoint', header: 'When', value: (r) => CHECKPOINT_LABEL[r.checkpoint] ?? r.checkpoint },
    { key: 'size', header: 'Order size', value: (r) => r.size, render: (r) => `${r.size} contract${r.size === 1 ? '' : 's'}` },
    { key: 'group', header: keyHeader, value: keyValue },
    { key: 'median', header: 'Median cost per $10', value: (r) => r.median, render: (r) => money(r.median), className: num },
    { key: 'p25', header: 'Middle half from', value: (r) => r.p25, render: (r) => money(r.p25), className: num },
    { key: 'p75', header: 'to', value: (r) => r.p75, render: (r) => money(r.p75), className: num },
    { key: 'mean', header: 'Average', value: (r) => r.mean, render: (r) => money(r.mean), className: num },
    { key: 'gap', header: 'Gap part', value: (r) => r.gap_part, render: (r) => money(r.gap_part), className: num },
    { key: 'fee', header: 'Fee part', value: (r) => r.fee_part, render: (r) => money(r.fee_part), className: num },
    { key: 'cents', header: '¢ per contract', value: (r) => r.cents_per_contract, render: (r) => r.cents_per_contract.toFixed(2), className: num },
    { key: 'n', header: 'Bets counted', value: (r) => r.n, render: (r) => fmtNum(r.n), className: num },
  ]
  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(r) => `${r.checkpoint}|${r.size}|${String(keyValue(r))}`}
      csvName={csvName}
      maxHeight="max-h-80"
      empty={<EmptyState icon={Table2} title="No costs for this selection" />}
    />
  )
}

const QUALITY_TYPE_COLUMNS: Column<T3QualityByType>[] = [
  { key: 'type', header: 'Kind of bet', value: (r) => r.market_type },
  { key: 'markets', header: 'Bets', value: (r) => r.markets, className: num },
  { key: 'candles', header: 'Minutes stored', value: (r) => r.candles, render: (r) => fmtNum(r.candles), className: num },
  { key: 'missing', header: 'Bets with no candles', value: (r) => r.missing_candles, className: num },
  { key: 'not_fetched', header: 'Not downloaded yet', value: (r) => r.not_fetched, className: num },
  { key: 'crossed_m', header: 'Bets with bid above ask', value: (r) => r.markets_bid_above_ask, className: num },
  { key: 'crossed', header: 'Minutes with bid above ask', value: (r) => r.bid_above_ask, className: num },
  { key: 'wide', header: 'Minutes with gap ≥ 3¢', value: (r) => r.gap_3c_or_more, render: (r) => fmtNum(r.gap_3c_or_more), className: num },
  {
    key: 'wide_share',
    header: 'Share of two-sided minutes ≥ 3¢',
    value: (r) => (r.candles - r.one_sided > 0 ? r.gap_3c_or_more / (r.candles - r.one_sided) : null),
    render: (r) => (r.candles - r.one_sided > 0 ? `${((100 * r.gap_3c_or_more) / (r.candles - r.one_sided)).toFixed(1)}%` : '–'),
    className: num,
  },
  { key: 'one_sided', header: 'Minutes with one side empty', value: (r) => r.one_sided, render: (r) => fmtNum(r.one_sided), className: num },
  { key: 'errors', header: 'Fetch errors', value: (r) => r.fetch_errors, className: num },
]

export function QualityByTypeTable({ rows }: { rows: T3QualityByType[] }) {
  return (
    <DataTable
      columns={QUALITY_TYPE_COLUMNS}
      rows={rows}
      rowKey={(r) => r.market_type}
      csvName="task3-quality-by-type.csv"
      empty={<EmptyState icon={Table2} title="Nothing checked yet" />}
    />
  )
}

const QUALITY_MARKET_COLUMNS: Column<T3QualityMarket>[] = [
  { key: 'ticker', header: 'Bet code', value: (r) => r.ticker, className: 'font-mono' },
  { key: 'type', header: 'Kind', value: (r) => r.market_type },
  { key: 'week', header: 'Week', value: (r) => r.week, className: num },
  { key: 'status', header: 'Status', value: (r) => r.status },
  { key: 'open', header: 'Opened', value: (r) => r.open_utc, render: (r) => fmtUtc(r.open_utc, false) },
  { key: 'through', header: 'Downloaded up to', value: (r) => r.fetched_through_utc, render: (r) => fmtUtc(r.fetched_through_utc, false) },
  { key: 'candles', header: 'Minutes', value: (r) => r.candles, className: num },
  { key: 'crossed', header: 'Bid above ask', value: (r) => r.bid_above_ask, className: num },
  { key: 'wide', header: 'Gap ≥ 3¢', value: (r) => r.gap_3c_or_more, className: num },
  {
    key: 'wide_share',
    header: 'Share ≥ 3¢',
    value: (r) => r.gap_3c_share,
    render: (r) => (r.gap_3c_share === null ? '–' : `${(r.gap_3c_share * 100).toFixed(1)}%`),
    className: num,
  },
  { key: 'error', header: 'Last fetch error', value: (r) => r.last_error },
]

export function QualityMarketsTable({ rows, csvName, emptyTitle }: { rows: T3QualityMarket[]; csvName: string; emptyTitle: string }) {
  return (
    <DataTable
      columns={QUALITY_MARKET_COLUMNS}
      rows={rows}
      rowKey={(r) => r.ticker}
      csvName={csvName}
      maxHeight="max-h-72"
      empty={<p className="text-xs text-muted-foreground">{emptyTitle}</p>}
    />
  )
}
