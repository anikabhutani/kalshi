import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Activity, CheckCircle2, CircleMinus, CircleX, Play, TriangleAlert } from 'lucide-react'
import { ingameApi, type IGCheck, type IGFacts, type IGResults, type IGSeason } from '@/lib/api'
import { fmtNum, fmtUtc } from '@/lib/format'
import { navItem } from '@/lib/nav'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Chart } from '@/components/charts/Chart'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { PageShell, Section } from '@/components/PageShell'
import { StatTile } from '@/components/StatTile'
import {
  brierFigure,
  costFigure,
  feeRateFigure,
  liquidityFigure,
  phaseGroupFigure,
  reliabilityFigure,
  returnsFigure,
  slotFigure,
  timelineFigure,
} from '@/components/ingame/figures'

const ITEM = navItem('/ingame')

const pct = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
const usd = (v: number | null | undefined, d = 2) => (v == null ? '—' : `${v < 0 ? '−' : ''}$${Math.abs(v).toFixed(d)}`)
const signed = (v: number | null | undefined) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}$${Math.abs(v).toFixed(2)}`)
const millions = (v: number | null | undefined) =>
  v == null ? '—' : v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : `$${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)}M`

const STATUS: Record<IGCheck['status'], { icon: ReactNode; label: string; className: string }> = {
  pass: { icon: <CheckCircle2 className="size-3.5 shrink-0 text-primary" />, label: 'pass', className: 'text-primary' },
  warn: { icon: <TriangleAlert className="size-3.5 shrink-0 text-warning" />, label: 'warning', className: 'text-warning' },
  skip: { icon: <CircleMinus className="size-3.5 shrink-0 text-muted-foreground" />, label: 'skipped', className: 'text-muted-foreground' },
  fail: { icon: <CircleX className="size-3.5 shrink-0 text-destructive" />, label: 'FAILED', className: 'text-destructive' },
}

/** "Median bid-ask spread: 1.0¢ in every price group, before and during games", or each value if they differ. */
function spreadNote(s: Record<string, number>): string {
  const vals = Object.values(s)
  if (!vals.length) return ''
  if (vals.every((v) => v === vals[0])) return `Median bid-ask spread: ${vals[0]!.toFixed(1)}¢ in every price group, before and during games.`
  return `Median bid-ask spread: ${Object.entries(s)
    .map(([k, v]) => `${k.replace('|', ', ').replace(/ \(.*\)/, '')} ${v.toFixed(1)}¢`)
    .join(' · ')}`
}

/** Does a 95% interval include zero? */
const spansZero = (ci?: [number, number]) => !ci || (ci[0] <= 0 && ci[1] >= 0)

function Findings({ t, seasons }: { t: IGFacts; seasons: IGSeason[] }) {
  const ci = t.taker_after_ci?.['In-game']
  const brier = seasons.map((s) => s.facts).filter((f) => f.brier)
  const items: ReactNode[] = [
    <>
      <b>The game itself is the market.</b> {pct(t.inplay_dollar_share)} of the money and {pct(t.inplay_fee_share)} of Kalshi’s
      estimated fees on {t.season} NFL game-winner markets came after kickoff. The busiest half hour is {t.peak_bin} ({pct(t.peak_bin_share)} of all dollars).
    </>,
    <>
      <b>In-game longshots pay for the most.</b> Bets on the side under 40¢ during the game are {pct(t.inplay_longshot_dollar_share)} of the money but{' '}
      {pct(t.inplay_longshot_fee_share)} of fees, because the fee (0.07 × p × (1 − p) per contract) is largest relative to a cheap contract.
    </>,
    <>
      <b>Late-game trading is cheap for Kalshi’s revenue.</b> {pct(t.near_certain?.dollar_share_90_plus)} of in-game dollars buy a side already priced
      90¢ or more, but they bring only {pct(t.near_certain?.fee_share_90_plus)} of in-game fees; fee per $10 falls from {usd(t.fee_per_10_pre, 3)} before
      kickoff to {usd(t.late_fee_per_10, 3)} in the 150–180 minute window.
    </>,
    <>
      <b>In-game prices look fair to the bettor before fees.</b> Across {t.returns_games} settled games, in-game takers made{' '}
      {signed(t.taker_before_fees?.['In-game'])} per $10 before fees and {signed(t.taker_after_fees?.['In-game'])} after (95% range{' '}
      {ci ? `${signed(ci[0])} to ${signed(ci[1])}` : '—'}){spansZero(ci) ? ', which is not distinguishable from zero: no edge either way that this many games can detect.' : '.'}
    </>,
    brier.length > 0 && (
      <>
        <b>Prices get steadily more accurate as the game unfolds.</b>{' '}
        {brier.map((f) => `${f.season}: Brier ${f.brier!['-60']?.toFixed(3)} an hour before kickoff → ${f.brier!['120']?.toFixed(3)} two hours in`).join('; ')}{' '}
        (0.25 = coin flip). Accuracy at 150+ minutes is biased toward close or long games, which are the only ones still trading then.
      </>
    ),
    t.prime_inplay_per_game != null && t.day_inplay_per_game != null && (
      <>
        <b>Prime time drives in-game volume.</b> Thursday, Sunday and Monday night games trade {millions(t.prime_inplay_per_game)} per game in-game vs{' '}
        {millions(t.day_inplay_per_game)} for Sunday afternoon games ({(t.prime_inplay_per_game / t.day_inplay_per_game).toFixed(1)}×). The top 10 games hold{' '}
        {pct(t.top10_inplay_share)} of all in-game dollars.
      </>
    ),
  ].filter(Boolean)
  return (
    <Section title="What the data shows" description="Every sentence is built from the results below; nothing is typed in by hand.">
      <ol className="grid list-decimal gap-2 pl-5 text-sm leading-relaxed">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ol>
    </Section>
  )
}

function Tiles({ t }: { t: IGFacts }) {
  const ci = t.taker_after_ci?.['In-game']
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatTile label={`Money traded in-game (${t.season})`} value={pct(t.inplay_dollar_share)} tone="primary" hint={`of ${millions(t.dollars)} traded`} />
      <StatTile label="Fees earned in-game" value={pct(t.inplay_fee_share)} tone="primary" hint={`of ${millions(t.fees)} estimated fees`} />
      <StatTile label="Fee per $10, pre-game → in-game" value={`${usd(t.fee_per_10_pre, 2)} → ${usd(t.fee_per_10_in, 2)}`} />
      <StatTile label="In-game taker result after fees" value={signed(t.taker_after_fees?.['In-game'])} hint={ci ? `95% range ${signed(ci[0])} to ${signed(ci[1])}` : undefined} />
      <StatTile label="In-game median trade" value={`${t.sizes?.['In-game']?.median?.toFixed(0)} contracts`} hint={`pre-game ${t.sizes?.['Pre-game']?.median?.toFixed(0)}`} />
      <StatTile label="Prime-time vs daytime in-game $" value={t.prime_inplay_per_game && t.day_inplay_per_game ? `${(t.prime_inplay_per_game / t.day_inplay_per_game).toFixed(1)}×` : '—'} />
    </div>
  )
}

function ChecksSection({ results }: { results: IGResults }) {
  const ids = [...new Set(results.seasons.flatMap((s) => s.checks.map((c) => c.id)))]
  return (
    <Section
      title="Self-checks"
      description="Run after every calculation. Each recomputes a result a second way or tests an assumption, and names the mistake it guards against. A failed check means a number here can’t be trusted."
      actions={
        <div className="flex flex-wrap gap-2">
          {results.seasons.map((s) => (
            <Badge key={s.season} variant="outline">
              {s.season}: {s.checks.filter((c) => c.status === 'pass').length} pass
              {s.checks.some((c) => c.status === 'fail') && `, ${s.checks.filter((c) => c.status === 'fail').length} FAILED`}
            </Badge>
          ))}
        </div>
      }
    >
      <div className="grid gap-3">
        {ids.map((id) => {
          const rows = results.seasons.map((s) => ({ season: s.season, check: s.checks.find((c) => c.id === id) }))
          const first = rows.find((r) => r.check)?.check
          if (!first) return null
          return (
            <div key={id} className="rounded-lg border bg-surface px-3 py-2.5">
              <div className="text-sm font-medium">{first.title}</div>
              {first.guards_against && <div className="mb-1.5 text-xs text-muted-foreground">Guards against: {first.guards_against}</div>}
              <div className="grid gap-1">
                {rows.map(({ season, check }) =>
                  check ? (
                    <div key={season} className="flex items-start gap-2 text-xs">
                      {STATUS[check.status].icon}
                      <span className="w-10 shrink-0 font-mono">{season}</span>
                      <span className={`w-16 shrink-0 ${STATUS[check.status].className}`}>{STATUS[check.status].label}</span>
                      <span className="text-muted-foreground">{check.detail}</span>
                    </div>
                  ) : null,
                )}
              </div>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

function SizesTable({ s }: { s: IGSeason }) {
  type Row = NonNullable<IGSeason['trades']>['sizes'][number]
  const columns: Column<Row>[] = [
    { key: 'phase', header: 'When', value: (r) => r.phase },
    { key: 'trades', header: 'Trades', value: (r) => r.trades, render: (r) => fmtNum(r.trades) },
    { key: 'median', header: 'Median contracts', value: (r) => r.median, render: (r) => r.median?.toFixed(1) },
    { key: 'p75', header: 'p75', value: (r) => r.p75, render: (r) => r.p75?.toFixed(1) },
    { key: 'p90', header: 'p90', value: (r) => r.p90, render: (r) => r.p90?.toFixed(1) },
    { key: 'md', header: 'Median $', value: (r) => r.median_dollars, render: (r) => usd(r.median_dollars) },
    { key: 'p90d', header: 'p90 $', value: (r) => r.p90_dollars, render: (r) => usd(r.p90_dollars) },
    { key: 'small', header: '≤1 contract', value: (r) => r.share_1_or_less, render: (r) => pct(r.share_1_or_less, 1) },
  ]
  return <DataTable columns={columns} rows={s.trades!.sizes} rowKey={(r) => r.phase} csvName={`ingame-sizes-${s.season}.csv`} empty="No trades" />
}

function RoundingTable({ s }: { s: IGSeason }) {
  type Row = NonNullable<IGSeason['trades']>['rounding'][number]
  const columns: Column<Row>[] = [
    { key: 'phase', header: 'When', value: (r) => r.phase },
    { key: 'size', header: 'Trade size (contracts)', value: (r) => r.size_label },
    { key: 'trades', header: 'Trades', value: (r) => r.trades, render: (r) => fmtNum(r.trades) },
    { key: 'fee', header: 'Fees paid', value: (r) => r.fee, render: (r) => `$${fmtNum(Math.round(r.fee))}` },
    { key: 'extra', header: 'Extra from rounding up', value: (r) => r.rounding_extra, render: (r) => pct(r.rounding_extra, 1) },
  ]
  return <DataTable columns={columns} rows={s.trades!.rounding} rowKey={(r) => `${r.phase}|${r.size_label}`} csvName={`ingame-rounding-${s.season}.csv`} empty="No trades" />
}

function RunButton() {
  const qc = useQueryClient()
  const run = useMutation({
    mutationFn: ingameApi.run,
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['ingame'] })
      const failed = r.seasons.reduce((n, s) => n + s.checks_failed, 0)
      if (failed) toast.error(`Done in ${r.seconds} s; ${failed} self-check(s) failed.`)
      else toast.success(`Done in ${r.seconds} s. All self-checks passed.`)
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Run failed.'),
  })
  return (
    <Button size="sm" onClick={() => run.mutate()} disabled={run.isPending}>
      <Play className="mr-1 size-3.5" /> {run.isPending ? 'Running…' : 'Recompute'}
    </Button>
  )
}

function Body({ results }: { results: IGResults }) {
  const [afterFees, setAfterFees] = useState(true)
  const seasons = results.seasons
  const traded = seasons.filter((s) => s.trades)
  const latest = traded.at(-1)
  const f = latest?.facts
  return (
    <>
      {f && <Tiles t={f} />}
      {f && <Findings t={f} seasons={seasons} />}

      {latest && (
        <>
          <Section
            title="1. When the money and the fees come in"
            description={`${latest.season}: ${fmtNum(f!.trades ?? 0)} game-winner trades, ${millions(f!.dollars)} traded, ${millions(f!.fees)} in estimated taker fees (Kalshi’s fee formula on each fill, rounded up to the cent; maker fees not included). Kickoff from Kalshi’s game start times.`}
          >
            <div className="grid gap-4 xl:grid-cols-2">
              <Chart {...timelineFigure(latest)} filename={`ingame-${latest.season}-timeline`} />
              <Chart {...feeRateFigure(latest)} filename={`ingame-${latest.season}-fee-rate`} />
            </div>
          </Section>

          <Section
            title="2. Where the fees come from: favorites, longshots, before and during the game"
            description="Price group of the side the taker bought, at the moment of the trade. Longshot under 40¢, favorite 60¢ and up (as in the team deck)."
          >
            <Chart {...phaseGroupFigure(latest)} filename={`ingame-${latest.season}-fee-sources`} />
          </Section>
        </>
      )}

      <Section
        title="3. What an in-game bet costs"
        description={`Median cost per $10 of buying ${seasons[0]?.n_contracts ?? 24} contracts at the ask (the median trade size), with the fair price at the bid-ask midpoint: the fee plus half the spread. Pre-game = last hour; in-game = first three hours. A 1¢ spread and the fee weigh more on a cheap contract, and in-game longshots are cheaper contracts than pre-game ones.`}
      >
        <div className="grid gap-6 xl:grid-cols-2">
          {seasons.map((s) => (
            <div key={s.season} className="grid gap-2">
              <Badge className="w-fit">{s.season} season</Badge>
              <Chart {...costFigure(s)} filename={`ingame-${s.season}-cost`} />
              <p className="text-xs text-muted-foreground">
                {spreadNote(s.facts.spread_phase_group ?? {})}
              </p>
              <Chart {...liquidityFigure(s)} filename={`ingame-${s.season}-two-sided`} />
              <p className="text-xs text-muted-foreground">
                Lower chart: share of markets with both a buy and a sell price. Late in games one side often disappears (the result is nearly certain), so costs there use fewer markets.
              </p>
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="4. Do in-game prices predict the winner?"
        description="One market per game (the away team’s), its mid price at each moment vs how the game ended. Brier score = average squared miss; 0.25 is a coin flip, 0 is perfect. Bars are 95% ranges from resampling games. After 150 minutes only unfinished games remain (close or long games), so those points are not comparable with earlier ones."
      >
        <Chart {...brierFigure(seasons)} filename="ingame-brier" />
        <div className="mt-4 grid gap-6 xl:grid-cols-2">
          {seasons.map((s) => (
            <div key={s.season} className="grid gap-1">
              <Badge className="w-fit">{s.season}: prices vs results</Badge>
              <Chart {...reliabilityFigure(s)} filename={`ingame-${s.season}-reliability`} />
              <p className="text-xs text-muted-foreground">
                Points on the dashed line mean prices were right on average (e.g. teams priced at 70% won 70% of the time). Calibration slope (1 = right on average):{' '}
                {s.calibration.by_checkpoint
                  .filter((c) => [-60, 60, 120].includes(c.minute))
                  .map((c) => `${c.minute < 0 ? '1 h before' : `${c.minute} min`} ${c.slope.toFixed(2)}`)
                  .join(', ')}
                .
              </p>
            </div>
          ))}
        </div>
      </Section>

      {latest && (
        <>
          <Section
            title="5. Do in-game bettors win or lose?"
            description={`What the side that crossed the spread (the taker) ended up with per $10 staked, on settled markets (${latest.trades!.returns_games} games, ties left out). Bars are 95% ranges from resampling whole games. With this many games, outcomes are noisy: a range that crosses $0 means no edge can be detected.`}
            actions={
              <div className="flex gap-1">
                <Button size="sm" variant={afterFees ? 'outline' : 'default'} onClick={() => setAfterFees(false)}>before fees</Button>
                <Button size="sm" variant={afterFees ? 'default' : 'outline'} onClick={() => setAfterFees(true)}>after fees</Button>
              </div>
            }
          >
            <Chart {...returnsFigure(latest, afterFees)} filename={`ingame-${latest.season}-taker-results`} />
          </Section>

          <Section title="6. Prime time" description="Dollars traded per game, by kickoff slot (Eastern time).">
            <Chart {...slotFigure(latest)} filename={`ingame-${latest.season}-slots`} />
          </Section>

          <Section
            title="7. Trade sizes and fee rounding"
            description={`Kalshi rounds the fee up to the cent on every fill, so tiny trades pay far more than the formula: overall the rounding adds ${pct(f!.rounding_total, 2)} to fees.`}
          >
            <div className="grid gap-6">
              <SizesTable s={latest} />
              <RoundingTable s={latest} />
            </div>
          </Section>
        </>
      )}

      {!latest && (
        <p className="text-sm text-muted-foreground">
          No trades saved yet: sections 1, 2, 5, 6 and 7 need <code>make trade-sizes SEASON=2026</code>. Sections 3 and 4 use Task 3 prices only.
        </p>
      )}

      <ChecksSection results={results} />
      <p className="text-xs text-muted-foreground">
        <Badge variant="outline" className="mr-2">numbers only</Badge>
        Calculated {fmtUtc(results.generated_at, false)}. Trades exist for {traded.map((s) => s.season).join(', ') || 'no season'} so far; prices and results for{' '}
        {seasons.map((s) => s.season).join(' and ')}.
      </p>
    </>
  )
}

export function InGamePage() {
  const results = useQuery({ queryKey: ['ingame', 'results'], queryFn: ingameApi.results })
  const data = results.data && results.data.seasons?.length ? results.data : null
  return (
    <PageShell item={ITEM}>
      <div className="flex justify-end">
        <RunButton />
      </div>
      {results.isLoading ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : data ? (
        <Body results={data} />
      ) : (
        <EmptyState icon={Activity} title="No results yet">
          Run <code>make ingame</code> (or press Recompute). It needs the saved trades (<code>make trade-sizes SEASON=2026</code>) and the Task 3 prices.
        </EmptyState>
      )}
    </PageShell>
  )
}
