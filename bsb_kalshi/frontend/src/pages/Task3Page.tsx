import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CalendarClock, CheckCircle2, CircleDashed, Copy, Download, ListChecks, Play, Receipt, RefreshCw, TriangleAlert } from 'lucide-react'
import {
  t3Api,
  type T3BackfillParams,
  type T3FeeRounding,
  type T3InventoryParams,
  type T3Results,
  type T3State,
} from '@/lib/api'
import { fmtNum, fmtUtc } from '@/lib/format'
import { navItem } from '@/lib/nav'
import { useGuardedRun } from '@/hooks/useGuardedRun'
import { useModuleJob } from '@/hooks/useModuleJob'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Chart } from '@/components/charts/Chart'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { NativeSelect } from '@/components/NativeSelect'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { RunConfirmDialog } from '@/components/RunConfirmDialog'
import { StatTile } from '@/components/StatTile'
import {
  CHECKPOINT_LABEL,
  gapFigure,
  kickoffFigure,
  marketTypeFigure,
  priceGroupFigure,
  weekFigure,
} from '@/components/task3/figures'
import {
  CostTable,
  CutoffSamplesTable,
  GamesTable,
  QualityByTypeTable,
  QualityMarketsTable,
} from '@/components/task3/Task3Tables'

const ITEM = navItem('/task3')

type StepState = 'done' | 'partial' | 'todo'

function StepIcon({ state }: { state: StepState }) {
  if (state === 'done') return <CheckCircle2 className="size-4 shrink-0 text-primary" />
  if (state === 'partial') return <CircleDashed className="size-4 shrink-0 text-warning" />
  return <CircleDashed className="size-4 shrink-0 text-muted-foreground" />
}

function Brief({ state, results }: { state: T3State; results: T3Results | null }) {
  const inv = state.inventory
  const t = state.totals
  const downloaded = t.markets_settled > 0 && t.markets_settled_complete === t.markets_settled
  const steps: { text: string; state: StepState; detail: string }[] = [
    {
      text: 'List every NFL event and market since Sept 14 in the game, spread and total series, including settled ones',
      state: inv ? 'done' : 'todo',
      detail: inv
        ? `${inv.games} games, ${inv.events} events, ${fmtNum(inv.markets)} markets (${fmtNum(inv.markets_settled)} settled), kickoff on or after ${inv.start_date}.`
        : 'Not listed yet.',
    },
    {
      text: 'Write backfill.py: 1-minute candles (best bid, best ask, volume, open interest) for every market, open to settlement, with the batch endpoint; save raw',
      state: 'done',
      detail: `backend/app/task3/backfill.py. Raw responses are saved gzip-compressed in ${state.storage.raw}.`,
    },
    {
      text: 'Run it for all NFL markets; check how Kalshi’s historical cutoff treats older settled markets',
      state: downloaded && state.cutoff_check ? 'done' : t.candles > 0 || state.cutoff_check ? 'partial' : 'todo',
      detail: `${fmtNum(t.markets_settled_complete)} of ${fmtNum(t.markets_settled)} settled markets fully downloaded, ${fmtNum(t.candles)} minutes stored. ${fmtNum(t.markets - t.markets_settled)} markets on upcoming games are caught up by the daily run (${
        state.next_backfill_requests === 0 ? 'nothing to fetch right now' : `${fmtNum(state.next_backfill_requests)} requests next run`
      }). Cutoff check ${state.cutoff_check ? 'done' : 'not run'}.`,
    },
    {
      text: 'Compute costs from the candles: half the gap plus the fee, at 1, 10 and 100 contracts, 24 h, 3 h, 1 h and 15 min before kickoff',
      state: results ? 'done' : 'todo',
      detail: results ? `${fmtNum(results.counts.quotes_ok)} usable quotes, ${fmtNum(results.counts.cost_rows)} bet costs.` : 'Runs after the backfill.',
    },
    {
      text: 'Quality check on our own data: markets missing candles, bid above ask, gaps of 3¢ or more',
      state: results ? 'done' : 'todo',
      detail: results
        ? `${fmtNum(results.quality.missing_candles_total)} markets without candles, ${fmtNum(results.quality.bid_above_ask_total)} with bid above ask, ${fmtNum(results.quality.totals.gap_3c_or_more ?? 0)} minutes with a gap of 3¢ or more.`
        : 'Runs after the backfill.',
    },
    {
      text: 'Results: cost per $10 bet by price group, market type and week; how costs change as kickoff gets closer. Plain charts of those results',
      state: results ? 'done' : 'todo',
      detail: results ? `Calculated ${fmtUtc(results.generated_at, false)}.` : 'Runs after the backfill.',
    },
    {
      text: 'Make backfill.py pick up new games each day without re-pulling old ones',
      state: state.last_run ? 'done' : 'partial',
      detail: state.last_run
        ? `Last run ${fmtUtc(state.last_run.finished_at, false)} from the ${state.last_run.source}, ${fmtNum(state.last_run.requests)} requests. Fully downloaded settled markets are skipped.`
        : 'Each market remembers how far it was downloaded; schedule the command below to run daily.',
    },
  ]
  return (
    <Section title="Task 3 · Abhi (Senior): Kalshi costs for every NFL game this season" description="The request, step by step, with where each step stands.">
      <ol className="grid gap-2.5">
        {steps.map((s, i) => (
          <li key={s.text} className="flex gap-2.5 text-sm">
            <StepIcon state={s.state} />
            <div className="grid gap-0.5">
              <span>
                <span className="mr-1.5 font-mono text-xs text-muted-foreground">{i + 1}.</span>
                {s.text}
              </span>
              <span className="text-xs text-muted-foreground">{s.detail}</span>
            </div>
          </li>
        ))}
      </ol>
    </Section>
  )
}

function ListSection({ state }: { state: T3State }) {
  const [overrides, setOverrides] = useState<Partial<T3InventoryParams>>({})
  const params: T3InventoryParams = { ...state.defaults.inventory, ...overrides }
  const set = (patch: Partial<T3InventoryParams>) => setOverrides((prev) => ({ ...prev, ...patch }))
  const job = useModuleJob<unknown>('T3', 'inventory')
  const guarded = useGuardedRun<T3InventoryParams>({
    plan: async (p) => (await t3Api.inventoryPlan(p)).estimate,
    run: t3Api.runInventory,
    onStarted: job.start,
  })
  const inv = state.inventory
  const toggle = (s: string) =>
    set({ series: params.series.includes(s) ? params.series.filter((x) => x !== s) : [...params.series, s] })

  return (
    <Section
      title="1. Every NFL game, spread and total bet since the start date"
      description="Lists every game in Kalshi’s NFL game-winner, spread and total-points series with kickoff on or after the start date (US Eastern), settled ones included. Kickoff time and week come from Kalshi’s game schedule (milestones). Also re-reads the fee settings and the archive cutoff, then runs the cutoff check below."
      actions={
        <Button size="lg" disabled={params.series.length === 0 || guarded.busy || job.running} onClick={() => guarded.request(params)}>
          <ListChecks /> List games
        </Button>
      }
    >
      <div className="grid gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="t3-start">First kickoff date</Label>
            <Input id="t3-start" type="date" value={params.start_date} onChange={(e) => set({ start_date: e.target.value })} className="w-40 font-mono" />
          </div>
          <div className="grid gap-1.5">
            <Label>Series</Label>
            <div className="flex h-9 flex-wrap items-center gap-3 text-sm">
              {Object.entries(state.series).map(([ticker, label]) => (
                <label key={ticker} className="flex items-center gap-1.5" title={ticker}>
                  <input type="checkbox" className="accent-primary" checked={params.series.includes(ticker)} onChange={() => toggle(ticker)} />
                  {label} <span className="font-mono text-xs text-muted-foreground">{ticker}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t3-list-cap">Max requests</Label>
            <Input
              id="t3-list-cap"
              type="number"
              min={20}
              max={500}
              value={params.request_cap}
              onChange={(e) => set({ request_cap: Math.min(500, Math.max(20, Number(e.target.value) || 20)) })}
              className="w-28 font-mono"
            />
          </div>
        </div>
        {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
        {inv && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <StatTile label="Games" value={inv.games} hint={`${inv.games_without_milestone} without a schedule entry (kickoff estimated)`} />
              <StatTile label="Events" value={inv.events} />
              <StatTile label="Markets (bets)" value={fmtNum(inv.markets)} />
              <StatTile label="Settled" value={fmtNum(inv.markets_settled)} />
              {Object.entries(inv.markets_by_type).map(([type, n]) => (
                <StatTile key={type} label={type} value={fmtNum(n)} />
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Listed {fmtUtc(inv.listed_at, false)}: {fmtNum(inv.new_markets)} new, {fmtNum(inv.known_markets)} already known.{' '}
              {inv.events_listed_from_archive > 0 && `${inv.events_listed_from_archive} events came from the archive. `}
              {inv.events_before_start_skipped > 0 && `${inv.events_before_start_skipped} events with kickoff before the start date were left out.`}
            </p>
          </>
        )}
        <GamesTable games={state.games} />
      </div>
      <RunConfirmDialog
        open={guarded.dialogOpen}
        onOpenChange={(open) => !open && guarded.closeDialog()}
        title="List NFL games and check the archive cutoff"
        estimate={guarded.estimate}
        breakdown={[
          { label: 'Listing (cutoff, fees, schedule, events)', value: guarded.estimate?.listing ?? 0 },
          { label: 'Archive cutoff check', value: guarded.estimate?.cutoff_check ?? 0 },
        ]}
        notes={['Does not download candles; that is the next step.']}
        onConfirm={guarded.confirm}
        confirming={guarded.confirming}
      />
    </Section>
  )
}

function CutoffSection({ state }: { state: T3State }) {
  const check = state.cutoff_check
  return (
    <Section
      title="2. How Kalshi’s archive cutoff treats older settled bets"
      description="Kalshi moves bets that settled before the cutoff date into a separate archive. We asked for three sample bets from the live system, the archive, and the batch candle endpoint used by the backfill."
    >
      {check === null ? (
        <EmptyState icon={CalendarClock} title="Not checked yet">
          Press “List games” above; the check runs right after the listing.
        </EmptyState>
      ) : (
        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            <StatTile label="Bets settled before this date are archived" value={fmtUtc(check.market_settled_ts, false)} />
            {Object.entries(check.our_markets_by_side).map(([side, n]) => (
              <StatTile key={side} label={`This season: ${side}`} value={fmtNum(n)} />
            ))}
          </div>
          <CutoffSamplesTable samples={check.samples} />
          <p className="max-w-4xl text-xs text-muted-foreground">
            The backfill uses the batch endpoint for every bet the live system lists, and the archive candle endpoint for bets only the
            archive lists. Checked {fmtUtc(check.checked_at, false)}. Other cutoff dates Kalshi reported:{' '}
            {Object.entries(check.cutoff)
              .map(([k, v]) => `${k} ${v}`)
              .join(', ')}
            .
          </p>
        </div>
      )}
    </Section>
  )
}

function CopyLine({ label, text }: { label: string; text: string }) {
  return (
    <div className="grid gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md bg-background/60 px-2 py-1.5 font-mono text-[11px]" title={text}>
          {text}
        </code>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void navigator.clipboard.writeText(text).then(() => toast.success('Copied.'))}
        >
          <Copy /> Copy
        </Button>
      </div>
    </div>
  )
}

function BackfillSection({ state }: { state: T3State }) {
  const [overrides, setOverrides] = useState<Partial<T3BackfillParams>>({})
  const params: T3BackfillParams = { ...state.defaults.backfill, ...overrides }
  const job = useModuleJob<unknown>('T3', 'backfill')
  const guarded = useGuardedRun<T3BackfillParams>({
    plan: async (p) => (await t3Api.backfillPlan(p)).estimate,
    run: t3Api.runBackfill,
    onStarted: job.start,
  })
  const t = state.totals
  const run = state.last_run?.candles ?? null

  return (
    <Section
      title="3. Download 1-minute prices (backfill)"
      description="For every listed bet, downloads one record per minute from when it opened until it settled: best buy price (bid), best sell price (ask), contracts traded and contracts outstanding. Uses Kalshi’s batch endpoint (up to 100 bets per request). Each bet remembers how far it was downloaded, so the next run only asks for new minutes and never re-downloads finished bets."
      actions={
        <Button size="lg" disabled={t.markets === 0 || guarded.busy || job.running} onClick={() => guarded.request(params)}>
          <Play /> Download prices
        </Button>
      }
    >
      <div className="grid gap-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile label="Bets fully downloaded" value={`${fmtNum(t.markets_complete)} / ${fmtNum(t.markets)}`} tone={t.markets_complete === t.markets && t.markets > 0 ? 'primary' : 'default'} />
          <StatTile label="Minutes stored" value={fmtNum(t.candles)} />
          <StatTile label="Requests the next run needs" value={fmtNum(state.next_backfill_requests)} hint="Still-open bets always need a few to catch up to now." />
          <StatTile label="Last run" value={state.last_run ? fmtUtc(state.last_run.finished_at, false).slice(0, 16) : '–'} hint={state.last_run?.source} />
        </div>
        {run?.stop_reason && (
          <p className="flex items-center gap-2 text-xs text-warning">
            <TriangleAlert className="size-3.5" /> Last run stopped early: {run.stop_reason}
          </p>
        )}
        <div className="flex flex-wrap items-end gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="t3-cap">Max requests</Label>
            <Input
              id="t3-cap"
              type="number"
              min={10}
              max={20000}
              value={params.request_cap}
              onChange={(e) => setOverrides((p) => ({ ...p, request_cap: Math.min(20000, Math.max(10, Number(e.target.value) || 10)) }))}
              className="w-28 font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t3-fee">Fee rounding for the cost step</Label>
            <NativeSelect
              id="t3-fee"
              value={params.fee_rounding}
              onChange={(e) => setOverrides((p) => ({ ...p, fee_rounding: e.target.value as T3FeeRounding }))}
              className="w-72"
            >
              <option value="cent">Round up to the next cent (fee schedule)</option>
              <option value="exact">Round up to $0.0001 (direct members)</option>
            </NativeSelect>
          </div>
        </div>
        {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
        <div className="grid gap-3 rounded-lg border bg-surface p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <CalendarClock className="size-4 text-primary" /> Daily update
          </div>
          <p className="text-xs text-muted-foreground">
            The same backfill runs from the command line: it re-lists games (new ones get added), downloads only the minutes that are
            missing, skips finished bets, and recomputes the results. Run it by hand, or add the second line to your crontab
            (<span className="font-mono">crontab -e</span>) to run it every morning at 9:15. The app does not need to be open.
          </p>
          <CopyLine label="Run now" text={state.daily.command} />
          <CopyLine label="Crontab line (daily at 9:15)" text={state.daily.cron} />
          <p className="text-xs text-muted-foreground">
            Stored in <span className="font-mono">{state.storage.database}</span>; raw responses in{' '}
            <span className="font-mono">{state.storage.raw}</span>.
          </p>
        </div>
      </div>
      <RunConfirmDialog
        open={guarded.dialogOpen}
        onOpenChange={(open) => !open && guarded.closeDialog()}
        title="Download 1-minute prices"
        estimate={guarded.estimate}
        breakdown={[{ label: 'Candle requests for bets not fully stored', value: guarded.estimate?.candles ?? 0 }]}
        notes={[
          'If it stops (request limit, rate limit or you press Stop), the next run continues where it left off.',
          'Costs and the quality check are recomputed at the end.',
        ]}
        onConfirm={guarded.confirm}
        confirming={guarded.confirming}
      />
    </Section>
  )
}

function QualitySection({ results }: { results: T3Results }) {
  const q = results.quality
  const totals = q.totals
  return (
    <Section
      title="4. Quality check on our stored data"
      description="Checks every stored minute: bets that have no prices at all, minutes where the best bid is above the best ask (should never happen), and minutes where the gap between bid and ask is 3¢ or more. Minutes where one side of the book is empty (no bid or no ask) are counted separately and left out of the gap check."
    >
      <div className="grid gap-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <StatTile label="Bets with no candles" value={q.missing_candles_total} tone={q.missing_candles_total > 0 ? 'warning' : 'primary'} />
          <StatTile label="Bets with bid above ask" value={q.bid_above_ask_total} tone={q.bid_above_ask_total > 0 ? 'warning' : 'primary'} />
          <StatTile label="Minutes with bid above ask" value={fmtNum(totals.bid_above_ask ?? 0)} />
          <StatTile label="Minutes with gap ≥ 3¢" value={fmtNum(totals.gap_3c_or_more ?? 0)} />
          <StatTile label="Minutes with one side empty" value={fmtNum(totals.one_sided ?? 0)} />
          <StatTile label="Bets still downloading" value={fmtNum(totals.incomplete ?? 0)} hint="Bets still open, or not fully downloaded yet." />
        </div>
        <QualityByTypeTable rows={q.by_market_type} />
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="grid gap-2">
            <h3 className="text-xs font-medium">Bets with no candles ({q.missing_candles_total})</h3>
            <QualityMarketsTable rows={q.missing_candles} csvName="task3-missing-candles.csv" emptyTitle="Every downloaded bet has candles." />
          </div>
          <div className="grid gap-2">
            <h3 className="text-xs font-medium">Bets with bid above ask ({q.bid_above_ask_total})</h3>
            <QualityMarketsTable rows={q.bid_above_ask} csvName="task3-bid-above-ask.csv" emptyTitle="No minute had the bid above the ask." />
          </div>
        </div>
        <div className="grid gap-2">
          <h3 className="text-xs font-medium">
            Bets by share of minutes with a gap of 3¢ or more ({q.wide_gap_markets_total}
            {q.wide_gap_markets_total > q.list_limit ? `, first ${q.list_limit} listed` : ''})
          </h3>
          <QualityMarketsTable rows={q.wide_gap_markets} csvName="task3-wide-gaps.csv" emptyTitle="No minute had a gap of 3¢ or more." />
        </div>
      </div>
    </Section>
  )
}

function CostsSection({ results }: { results: T3Results }) {
  const queryClient = useQueryClient()
  const [checkpoint, setCheckpoint] = useState('1h')
  const [size, setSize] = useState(10)
  const [rounding, setRounding] = useState<T3FeeRounding>(results.params.fee_rounding)
  const recompute = useMutation({
    mutationFn: () => t3Api.analyze(rounding),
    onSuccess: (data) => {
      queryClient.setQueryData(['t3', 'results'], data)
      void queryClient.invalidateQueries({ queryKey: ['t3', 'state'] })
      toast.success(`Recomputed in ${data.seconds} s.`)
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Recompute failed.'),
  })

  const price = useMemo(() => priceGroupFigure(results, checkpoint), [results, checkpoint])
  const types = useMemo(() => marketTypeFigure(results, checkpoint), [results, checkpoint])
  const weeks = useMemo(() => weekFigure(results, checkpoint, size), [results, checkpoint, size])
  const kickoff = useMemo(() => kickoffFigure(results, size), [results, size])
  const gaps = useMemo(() => gapFigure(results), [results])
  const at = CHECKPOINT_LABEL[checkpoint] ?? checkpoint

  return (
    <>
      <Section
        title="5. What a bet costs"
        description="Cost of placing a bet that is filled right away at the best price: half the gap between the best bid and best ask (what you give up versus the middle price), plus Kalshi’s fee of 7% × contracts × price × (1 − price), rounded up. Each bet can be bought as Yes (pay the ask) or No (pay 1 − bid); both are counted. Cost per $10 bet = 10 × cost ÷ (contracts × price paid). The quote at each time is the last 1-minute record at or before it."
        actions={
          <div className="flex flex-wrap items-end gap-2">
            <div className="grid gap-1">
              <Label htmlFor="t3-at" className="text-xs">When</Label>
              <NativeSelect id="t3-at" value={checkpoint} onChange={(e) => setCheckpoint(e.target.value)} className="w-44">
                {results.checkpoints.map((c) => (
                  <option key={c} value={c}>
                    {CHECKPOINT_LABEL[c] ?? c} kickoff
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-1">
              <Label htmlFor="t3-size" className="text-xs">Order size</Label>
              <NativeSelect id="t3-size" value={size} onChange={(e) => setSize(Number(e.target.value))} className="w-36">
                {results.sizes.map((s) => (
                  <option key={s} value={s}>
                    {s} contract{s === 1 ? '' : 's'}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-1">
              <Label htmlFor="t3-round" className="text-xs">Fee rounding</Label>
              <NativeSelect id="t3-round" value={rounding} onChange={(e) => setRounding(e.target.value as T3FeeRounding)} className="w-40">
                <option value="cent">to the cent</option>
                <option value="exact">to $0.0001</option>
              </NativeSelect>
            </div>
            <Button variant="outline" onClick={() => recompute.mutate()} disabled={recompute.isPending}>
              <RefreshCw className={recompute.isPending ? 'animate-spin' : undefined} /> Recompute
            </Button>
          </div>
        }
      >
        <div className="grid gap-2 text-xs text-muted-foreground">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">calculated {fmtUtc(results.generated_at, false)}</Badge>
            <Badge variant="outline">fee rounded {results.params.fee_rounding === 'cent' ? 'up to the cent' : 'up to $0.0001'}</Badge>
            <Badge variant="outline">{fmtNum(results.counts.quotes_ok)} usable quotes</Badge>
            {Object.entries(results.fee_types_used).map(([k, n]) => (
              <Badge key={k} variant="secondary" title="Kalshi fee type and multiplier in effect at the quote time">
                {k}: {fmtNum(n)}
              </Badge>
            ))}
            <a className="ml-auto inline-flex items-center gap-1 text-primary hover:underline" href={t3Api.exportUrl('checkpoint_costs.csv')}>
              <Download className="size-3.5" /> every bet cost (CSV)
            </a>
            <a className="inline-flex items-center gap-1 text-primary hover:underline" href={t3Api.exportUrl('checkpoint_quotes.csv')}>
              <Download className="size-3.5" /> every quote (CSV)
            </a>
          </div>
        </div>
      </Section>

      <Section title={`Cost per $10 bet by price paid, ${at} kickoff`} description="Median over every bet in that price range, for each order size. Cheap long shots cost the most per $10 because the fee and the gap are large compared to the price.">
        {price === null ? <EmptyState icon={Receipt} title="No costs for this time" /> : <Chart {...price} filename="task3-cost-by-price" />}
        <div className="mt-4">
          <CostTable
            rows={results.results.by_price_group.filter((r) => r.checkpoint === checkpoint)}
            keyHeader="Price paid"
            keyValue={(r) => r.price_group}
            csvName="task3-cost-by-price-group.csv"
          />
        </div>
      </Section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title={`Cost per $10 bet by kind of bet, ${at} kickoff`} description="Game winner, spread and total-points bets, and all three together.">
          {types === null ? <EmptyState icon={Receipt} title="No costs for this time" /> : <Chart {...types} filename="task3-cost-by-type" />}
        </Section>
        <Section title={`How costs change as kickoff gets closer (${size} contract${size === 1 ? '' : 's'})`} description="Median cost per $10 bet at 24 hours, 3 hours, 1 hour and 15 minutes before kickoff.">
          {kickoff === null ? <EmptyState icon={Receipt} title="No costs yet" /> : <Chart {...kickoff} filename="task3-cost-vs-kickoff" />}
        </Section>
      </div>

      <Section title="Cost by kind of bet and time before kickoff (table)" description="All four times and all three order sizes.">
        <CostTable rows={results.results.by_market_type} keyHeader="Kind of bet" keyValue={(r) => r.market_type} csvName="task3-cost-by-type.csv" />
      </Section>

      <Section title={`Cost per $10 bet by NFL week, ${at} kickoff (${size} contract${size === 1 ? '' : 's'})`} description="One line per kind of bet.">
        {weeks === null ? <EmptyState icon={Receipt} title="No costs for this selection" /> : <Chart {...weeks} filename="task3-cost-by-week" />}
        <div className="mt-4">
          <CostTable
            rows={results.results.by_week.filter((r) => r.checkpoint === checkpoint && r.size === size)}
            keyHeader="Week · kind"
            keyValue={(r) => `Week ${r.week} · ${r.market_type}`}
            csvName="task3-cost-by-week.csv"
          />
        </div>
      </Section>

      <Section title="Bid-ask gap as kickoff gets closer" description="Lines: median gap between best bid and best ask, in cents. Bars: share of quotes with a gap of 3¢ or more (right axis).">
        {gaps === null ? <EmptyState icon={Receipt} title="No quotes yet" /> : <Chart {...gaps} filename="task3-gap-vs-kickoff" />}
      </Section>
    </>
  )
}

export function Task3Page() {
  const state = useQuery({ queryKey: ['t3', 'state'], queryFn: t3Api.state })
  const results = useQuery({ queryKey: ['t3', 'results'], queryFn: t3Api.results })

  return (
    <PageShell item={ITEM}>
      {state.isLoading || state.data === undefined ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : (
        <>
          <Brief state={state.data} results={results.data ?? null} />
          <ListSection state={state.data} />
          <CutoffSection state={state.data} />
          <BackfillSection state={state.data} />
          {results.isLoading ? (
            <Skeleton className="h-96 w-full rounded-xl" />
          ) : results.data ? (
            <>
              <QualitySection results={results.data} />
              <CostsSection results={results.data} />
            </>
          ) : (
            <EmptyState icon={Receipt} title="No results yet">
              List the games, then download prices; the quality check and costs are calculated at the end.
            </EmptyState>
          )}
        </>
      )}
      <RawRequestsDrawer module="T3" />
    </PageShell>
  )
}
